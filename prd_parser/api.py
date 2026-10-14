"""FastAPI application for the PRD-to-Code test generation pipeline.

Exposes endpoints:
- POST /parse-prd: Parse PRD documents (PDF or Markdown)
- POST /generate-functional-tests: Generate functional tests from PRD and code context
- POST /validate-code: Validate code tests against PRD acceptance criteria
- GET /health: Health check
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Body
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from prd_parser.ast_parser import extract_structural_context
from prd_parser.code_test_generator import CodeTestPromptEngine, extract_structural_context_from_result
from prd_parser.verifier import verify
from prd_parser.models import PRDExtraction, FunctionalSpecification, AcceptanceCriterion, EdgeCaseAssumption

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("prd-api")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
logger.addHandler(handler)

# ---------------------------------------------------------------------------
# Caching (file-based; Redis-ready design)
# ---------------------------------------------------------------------------
CACHE_DIR = Path(".cache")
CACHE_DIR.mkdir(exist_ok=True)


def _cache_key(prefix: str, *parts: str) -> str:
    """Generate a deterministic cache key from parts."""
    return f"{prefix}:{':'.join(parts)}"


def _read_cache(key: str) -> Optional[Dict[str, Any]]:
    """Read cached result from disk."""
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Cache read error for {key}: {e}")
    return None


def _write_cache(key: str, data: Dict[str, Any]) -> None:
    """Write result to disk cache."""
    cache_file = CACHE_DIR / f"{key}.json"
    try:
        cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Cache write error for {key}: {e}")


# ---------------------------------------------------------------------------
# Request DTOs
# ---------------------------------------------------------------------------

class ParsePRDRequest(BaseModel):
    """Request body for /parse-prd."""
    source_format: str = Field(
        default="pdf",
        description="Input format: 'pdf' or 'markdown'.",
    )
    use_llm: bool = Field(
        default=True,
        description="Whether to use LLM for structured extraction.",
    )


class GenerateTestsRequest(BaseModel):
    """Request body for /generate-functional-tests."""
    prd_requirement_id: str = Field(..., description="PRD requirement ID")
    prd_functional_spec: str = Field(..., description="Functional specification text")
    prd_acceptance_criteria: List[str] = Field(
        default_factory=list,
        description="List of acceptance criterion strings",
    )
    prd_edge_case_assumptions: List[Dict[str, str]] = Field(
        default_factory=list,
        description="List of edge case assumption dicts",
    )
    code_source: str = Field(..., description="Python source code to analyze")
    language: str = Field(default="python", description="Programming language: python or javascript")


class ValidateCodeRequest(BaseModel):
    """Request body for /validate-code."""
    prd_requirement_id: str = Field(..., description="PRD requirement ID")
    prd_functional_spec: str = Field(..., description="Functional specification text")
    prd_acceptance_criteria: List[str] = Field(
        default_factory=list,
        description="List of acceptance criterion strings",
    )
    prd_edge_case_assumptions: List[Dict[str, str]] = Field(
        default_factory=list,
        description="List of edge case assumption dicts",
    )
    generated_tests: Dict[str, Any] = Field(
        ...,
        description="Generated test cases dict (from prompt engine output)",
    )
    code_structural_context: Dict[str, Any] = Field(
        ...,
        description="Structural context from code parsing (imports, functions, classes, logic blocks)",
    )


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PRD-to-Code Test Generation Pipeline",
    version="0.1.0",
    description=(
        "API for parsing PRDs, generating code-level functional tests (PyTest/Jest), "
        "and validating code compliance against PRD requirements."
    ),
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _parse_prd_text(prd_text: str, source_format: str = "pdf") -> Dict[str, Any]:
    """Parse PRD text into structured dict.

    Very simplified extraction - in production would use LLM or dedicated parsers.
    """
    # Try to find requirement ID pattern
    requirement_id = "REQ-001"  # default
    match = re.search(r"[Rr]eq[-_]?(\d{3,})", prd_text)
    if match:
        candidate = f"REQ-{match.group(1)}"
        # Validate format: must match REQ-NNN pattern
        if re.match(r"^REQ-\d{3,}$", candidate):
            requirement_id = candidate

    # Extract functional spec (first sentence-ish line)
    spec = ""
    sentences = [s.strip() for s in prd_text.split(". ") if s.strip()]
    if sentences:
        spec = sentences[0][:100]

    # Extract acceptance criteria (numbered lines starting with Given/When/Then)
    acceptance_criteria: List[str] = []
    for line in prd_text.split("\n"):
        line_stripped = line.strip()
        # Match numbered criteria like '1. Given ...' - capture just the number+period, get remainder
        m = re.match(r"^\d+\.", line_stripped)
        if m:
            # Get the remainder after the number+period (skip the space too)
            remainder = line_stripped[m.end() :].lstrip()
            if remainder.startswith(("Given ", "When ", "Then ")):
                acceptance_criteria.append(line_stripped)

    # Extract edge case assumptions (lines after "### Edge Case Assumptions" heading)
    edge_case_assumptions: List[Dict[str, str]] = []
    in_edge_section = False
    for line in prd_text.split("\n"):
        line_stripped = line.strip()
        # Detect the start of the edge case section
        if re.match(r"^###+\s*Edge Case", line_stripped, re.IGNORECASE):
            in_edge_section = True
            continue
        # If we're in the edge section and hit another heading, stop
        if in_edge_section and re.match(r"^###", line_stripped):
            in_edge_section = False
            continue
        # Collect assumption lines within the edge section
        if in_edge_section and line_stripped:
            # Skip heading lines within the section
            if not re.match(r"^###", line_stripped) and not re.match(r"^\d+\.", line_stripped):
                # Check if it looks like an assumption
                if ("assumption" in line_stripped.lower() or "concurrent" in line_stripped.lower() or "missing" in line_stripped.lower()):
                    edge_case_assumptions.append(
                        {
                            "assumption": line_stripped,
                            "context": "",
                            "impact": "",
                        }
                    )

    return {
        "requirement_id": requirement_id,
        "functional_specification": spec,
        "acceptance_criteria": acceptance_criteria,
        "edge_case_assumptions": edge_case_assumptions,
    }


def _generate_tests(prd_dict: Dict[str, Any], code_source: str, language: str = "python") -> Dict[str, Any]:
    """Generate functional tests from PRD + code context."""
    # Parse code context using AST
    code_result = extract_structural_context(code_source, "temp.py")
    code_ctx = code_result.structural_context

    # Build PRD extraction-like object for the prompt engine
    from prd_parser.models import PRDExtraction, FunctionalSpecification, AcceptanceCriterion

    # Ensure specification is not empty
    spec = prd_dict.get("functional_specification", "") or "User functionality"

    parsed_prd = PRDExtraction(
        requirement_id=prd_dict.get("requirement_id", "REQ-001"),
        functional_specification=FunctionalSpecification(
            specification=spec,
            category=prd_dict.get("category", ""),
            complexity=prd_dict.get("complexity", ""),
        ),
        acceptance_criteria=[
            AcceptanceCriterion(criterion=c) for c in prd_dict.get("acceptance_criteria", [])
        ],
        edge_case_assumptions=[
            EdgeCaseAssumption(
                assumption=a.get("assumption", ""), context=a.get("context", ""), impact=a.get("impact", "")
            )
            for a in prd_dict.get("edge_case_assumptions", [])
        ],
        source_format=prd_dict.get("source_format", "pdf"),
    )

    # Generate prompts using the prompt engine
    engine = CodeTestPromptEngine()
    prompt_result = engine.generate_pytest_tests(parsed_prd, code_ctx)

    return {
        "prompt": prompt_result["prompt"],
        "format": prompt_result["format"],
        "language": prompt_result["language"],
        "code_context": {
            "filename": code_ctx.filename,
            "functions": [f.name for f in code_ctx.functions],
            "classes": [c.name for c in code_ctx.classes],
            "logic_blocks": [b.block_type for b in code_ctx.logic_blocks],
        },
    }


def _validate_code(prd_dict: Dict[str, Any], code_ctx_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Validate generated tests against PRD requirements."""
    # Convert dict to PRDExtraction for verification
    from prd_parser.models import PRDExtraction, FunctionalSpecification, AcceptanceCriterion

    # Build PRDExtraction from dict
    prd = PRDExtraction(
        requirement_id=prd_dict.get("requirement_id", "REQ-001"),
        functional_specification=FunctionalSpecification(
            specification=prd_dict.get("functional_specification", ""),
            category=prd_dict.get("category", ""),
            complexity=prd_dict.get("complexity", ""),
        ),
        acceptance_criteria=[
            AcceptanceCriterion(criterion=c) for c in prd_dict.get("acceptance_criteria", [])
        ],
        edge_case_assumptions=[
            EdgeCaseAssumption(
                assumption=a.get("assumption", ""), context=a.get("context", ""), impact=a.get("impact", "")
            )
            for a in prd_dict.get("edge_case_assumptions", [])
        ],
        source_format=prd_dict.get("source_format", "pdf"),
    )

    # Convert dict to have generated_tests key
    test_data = prd_dict.copy()
    test_data["generated_tests"] = prd_dict.get("generated_tests", {})

    result = verify(prd, test_data["generated_tests"], code_ctx_dict)
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post(
    "/parse-prd",
    summary="Parse a PRD document (PDF or Markdown)",
    description=(
        "Accepts PRD text and extracts structured requirements including "
        "requirement ID, functional specification, acceptance criteria, and edge case assumptions."
    ),
)
async def parse_prd_endpoint(
    request: ParsePRDRequest = Body(...),
) -> Dict[str, Any]:
    """Parse PRD document endpoint.

    - **source_format**: Input format ('pdf' or 'markdown')
    - **use_llm**: Whether to use LLM for structured extraction
    """
    result = _parse_prd_text("", request.source_format)
    # Construct ParsePRDResponse-like output
    return {
        "requirement_id": result["requirement_id"],
        "functional_specification": result["functional_specification"],
        "acceptance_criteria": result["acceptance_criteria"],
        "edge_case_assumptions": result["edge_case_assumptions"],
        "source_format": request.source_format,
    }


@app.post(
    "/generate-functional-tests",
    summary="Generate functional tests from PRD and code context",
    description=(
        "Combines PRD requirements with code structural context to generate "
        "PyTest/Jest test prompts that verify the implementation fulfills the specifications."
    ),
)
async def generate_functional_tests_endpoint(
    request: GenerateTestsRequest = Body(...),
) -> Dict[str, Any]:
    """Generate functional tests endpoint.

    - **prd_requirement_id**: PRD requirement identifier
    - **prd_functional_spec**: Functional specification text
    - **prd_acceptance_criteria**: List of acceptance criterion strings
    - **prd_edge_case_assumptions**: List of edge case assumption dicts
    - **code_source**: Python source code to analyze for structural context
    - **language**: Programming language ('python' or 'javascript')
    """
    # Build PRD dict from request
    prd_dict = {
        "requirement_id": request.prd_requirement_id,
        "functional_specification": request.prd_functional_spec,
        "acceptance_criteria": request.prd_acceptance_criteria,
        "edge_case_assumptions": request.prd_edge_case_assumptions,
        "source_format": "pdf",
    }

    # Generate tests
    result = _generate_tests(prd_dict, request.code_source, request.language)
    return result


@app.post(
    "/validate-code",
    summary="Validate code tests against PRD requirements",
    description=(
        "Cross-evaluates generated code tests against PRD acceptance criteria, "
        "outputting a coverage score, missing assertions, discrepancies, and recommendations."
    ),
)
async def validate_code_endpoint(
    request: ValidateCodeRequest = Body(...),
) -> JSONResponse:
    """Validate code endpoint.

    - **prd_requirement_id**: PRD requirement identifier
    - **prd_functional_spec**: Functional specification text
    - **prd_acceptance_criteria**: List of acceptance criterion strings
    - **prd_edge_case_assumptions**: List of edge case assumption dicts
    - **generated_tests**: Generated test cases dict (from prompt engine output)
    - **code_structural_context**: Structural context from code parsing

    Returns validation verdict with coverage score, missing assertions, discrepancies,
    and recommendations.
    """
    # Build PRD dict from request
    prd_dict = {
        "requirement_id": request.prd_requirement_id,
        "functional_specification": request.prd_functional_spec,
        "acceptance_criteria": request.prd_acceptance_criteria,
        "edge_case_assumptions": request.prd_edge_case_assumptions,
        "generated_tests": request.generated_tests,
        "source_format": "pdf",
    }

    # Get code structural context
    code_ctx_dict = request.code_structural_context

    # Run validation
    result = _validate_code(prd_dict, code_ctx_dict)

    return JSONResponse(content=result)


@app.get(
    "/health",
    summary="Health check",
    description="Return API status.",
)
async def health_check() -> Dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok", "message": "PRD-to-Code API is running"}