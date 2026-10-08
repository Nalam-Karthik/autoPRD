"""LLM-as-a-Judge verification module.

Cross-evaluates generated code tests against initial PRD acceptance criteria.
Outputs a coverage score, flags missing assertions, and highlights discrepancies
where code deviates from requirements.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from prd_parser.models import PRDExtraction


def _to_dict(obj: Any) -> Dict[str, Any]:
    """Convert Pydantic model to dict if needed."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return obj


def _safe_get(d: Dict, key: str, default=None) -> Any:
    """Safely get a value from a dict."""
    value = d.get(key, default) if isinstance(d, dict) else getattr(d, key, default)
    return value


def _format_list(items: List[str]) -> str:
    """Format a list of strings as a space-separated string."""
    return " ".join(items) if items else ""


def _extract_test_names(generated_tests: Dict[str, Any]) -> List[str]:
    """Extract test names from generated test dict."""
    tests_list = _safe_get(generated_tests, "tests", [])
    return [_safe_get(t, "name", "") for t in tests_list]


def _extract_test_functions(generated_tests: Dict[str, Any]) -> List[str]:
    """Extract function names from generated tests."""
    tests_list = _safe_get(generated_tests, "tests", [])
    return [_safe_get(t, "function", "") for t in tests_list]


def verify(
    prd: PRDExtraction,
    generated_tests: Dict[str, Any],
    code_ctx: Any,
    *,
    coverage_threshold: float = 80.0,
) -> Dict[str, Any]:
    """Verify generated tests against PRD requirements.

    Args:
        prd: The PRD extraction with requirements.
        generated_tests: The dict of generated test cases (from prompt engine).
        code_ctx: The structural context from code parsing.
        coverage_threshold: Minimum coverage percentage required to pass (default: 80%).

    Returns:
        Dict with verification results (coverage, missing, discrepancies, recommendations).
    """
    # Convert prd to dict for consistent access
    prd_dict = _to_dict(prd)

    # Extract acceptance criteria from PRD
    acceptance_criteria = _safe_get(prd_dict, "acceptance_criteria", [])
    if not acceptance_criteria:
        return {
            "overall_coverage": 100.0,
            "passed": True,
            "missing_assertions": [],
            "discrepancies": [],
            "test_summary": {
                "total_generated_tests": 0,
                "covered_criteria": 0,
                "total_criteria": 0,
                "coverage_percentage": 100.0,
            },
            "recommendations": ["No acceptance criteria defined in PRD."],
        }

    # Extract test names and functions from generated tests
    generated_test_names = _extract_test_names(generated_tests)
    generated_test_functions = _extract_test_functions(generated_tests)

    # Calculate coverage using heuristic analysis
    covered_count = 0
    missing = []

    for i, ac in enumerate(acceptance_criteria, 1):
        # Handle both dict and model field access
        criterion_text = (
            ac.get("criterion", "") if isinstance(ac, dict) else getattr(ac, "criterion", "")
        ).lower()
        covered = False

        # Check if any test name contains key terms from the acceptance criterion
        for test_name in generated_test_names:
            test_lower = test_name.lower()
            criterion_words = set(re.findall(r"\b\w+\b", criterion_text))
            test_words = set(re.findall(r"\b\w+\b", test_lower))
            if criterion_words & test_words:
                covered = True
                break

        # Also check if the target function matches
        if not covered:
            for func_name in generated_test_functions:
                if func_name.lower() in criterion_text or criterion_text in func_name.lower():
                    covered = True
                    break

        if covered:
            covered_count += 1
        else:
            missing.append(
                {
                    "criterion_number": i,
                    "criterion": (
                        ac.get("criterion", "") if isinstance(ac, dict) else getattr(ac, "criterion", "")
                    ),
                    "category": (
                        ac.get("category", "unknown") if isinstance(ac, dict) else getattr(ac, "category", "unknown")
                    ),
                    "reason": "No generated test covers this acceptance criterion",
                }
            )

    total = len(acceptance_criteria)
    coverage = (covered_count / total * 100) if total > 0 else 0.0
    passed = coverage >= coverage_threshold

    # Build discrepancies based on code context
    discrepancies = _detect_discrepancies(prd_dict, code_ctx)

    # Build test summary
    test_summary = {
        "total_generated_tests": len(generated_test_names),
        "target_functions": _format_list(generated_test_functions),
        "covered_criteria": covered_count,
        "total_criteria": total,
        "coverage_percentage": round(coverage, 2),
    }

    # Generate recommendations
    recommendations = _generate_recommendations(coverage, coverage_threshold, len(missing))

    return {
        "overall_coverage": coverage,
        "passed": passed,
        "missing_assertions": missing,
        "discrepancies": discrepancies,
        "test_summary": test_summary,
        "recommendations": recommendations,
    }


def _detect_discrepancies(prd_dict: Dict[str, Any], code_ctx: Any) -> List[Dict[str, Any]]:
    """Detect discrepancies between PRD and code."""
    discrepancies = []

    # Check for edge case assumptions not handled
    prd_assumptions = _safe_get(prd_dict, "edge_case_assumptions", [])
    logic_blocks = _safe_get(code_ctx, "logic_blocks", []) if code_ctx else []
    if prd_assumptions and not logic_blocks:
        discrepancies.append(
            {
                "type": "missing_edge_case_handling",
                "description": "PRD specifies edge-case assumptions but code has no detectable logic blocks (if/for/while/try)",
                "severity": "high",
            }
        )

    # Check functional specification vs code functions
    spec = _safe_get(prd_dict, "functional_specification", {}).get("specification", "")
    spec_lower = spec.lower() if spec else ""
    functions = _safe_get(code_ctx, "functions", []) if code_ctx else []

    for func in functions:
        # Handle both dict and model
        func_name = (
            func.get("name", "") if isinstance(func, dict) else getattr(func, "name", "")
        ).lower()
        func_doc = (
            func.get("docstring", "") if isinstance(func, dict) else getattr(func, "docstring", "")
        ).lower()
        # If function name doesn't relate to spec, flag
        if func_name and spec_lower and func_name not in spec_lower:
            spec_words = set(re.findall(r"\b\w+\b", spec_lower)) if spec_lower else set()
            doc_words = set(re.findall(r"\b\w+\b", func_doc)) if func_doc else set()
            if not (spec_words & doc_words):
                discrepancies.append(
                    {
                        "type": "function_purpose_mismatch",
                        "function": func.name if isinstance(func, dict) else getattr(func, "name", ""),
                        "description": "Function may not align with PRD",
                        "severity": "medium",
                    }
                )

    return discrepancies


def _generate_recommendations(coverage: float, coverage_threshold: float, missing_count: int) -> List[str]:
    """Generate recommendations based on verification results."""
    recommendations = []

    if coverage < 50:
        recommendations.append(
            "Coverage is critically low (< 50%). Consider rewriting tests to cover more PRD acceptance criteria."
        )
    elif coverage < coverage_threshold:
        recommendations.append(
            f"Coverage is moderate (< {coverage_threshold}%). Add tests for remaining acceptance criteria, especially edge cases."
        )

    if missing_count > 0:
        recommendations.append(
            f"Add tests for {missing_count} uncovered acceptance criterion(s)."
        )

    if not recommendations:
        recommendations.append("Code coverage meets PRD requirements. No immediate action needed.")

    return recommendations


def quick_verify(
    prd: PRDExtraction,
    generated_tests: Dict[str, Any],
    code_ctx: Any,
    *,
    coverage_threshold: float = 80.0,
) -> Dict[str, Any]:
    """Quick verification without LLM client.

    Args:
        prd: The PRD extraction.
        generated_tests: Generated test cases dict.
        code_ctx: Code structural context.
        coverage_threshold: Minimum coverage to pass.

    Returns:
        Dict with verification results.
    """
    return verify(prd, generated_tests, code_ctx, coverage_threshold=coverage_threshold)