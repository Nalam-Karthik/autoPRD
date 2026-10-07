"""Prompt engine that combines PRD requirements with code context to generate
code-level unit/integration tests (PyTest for Python, Jest for JavaScript/TypeScript).

Compares implementation against specifications and generates tests that verify
the code logic fulfills the PRD.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

# JSON schema placeholder for LLM test generation output validation
JSON_SCHEMA_PLACEHOLDER = """{
  "type": "object",
  "properties": {
    "tests": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "function": {"type": "string"},
          "inputs": {"type": "object"},
          "expected": {"type": "object"},
          "description": {"type": "string"},
          "category": {"type": "string"}
        },
        "required": ["name", "function", "inputs", "expected"]
      }
    }
  },
  "required": ["tests"]
}"""

from prd_parser.models import (
    PRDExtraction,
    FunctionalSpecification,
    AcceptanceCriterion,
    EdgeCaseAssumption,
)
from prd_parser.ast_parser import (
    ASTExtractionResult,
    LogicBlock,
    structural_context_context,
)


class CodeTestPromptEngine:
    """Engine that generates code-level tests from PRD requirements and code context."""

    def __init__(self):
        pass

    def build_comparison_prompt(
        self,
        prd_extraction: PRDExtraction,
        code_context: structural_context_contextAST,
        language: str = "python",
    ) -> str:
        """Build a prompt that compares implementation against specifications.

        Args:
            prd_extraction: The PRD extraction with requirements.
            code_context: The structural context from code parsing.
            language: Programming language ("python" or "javascript"/"typescript").

        Returns:
            A formatted prompt string for the LLM.
        """
        # Format PRD sections
        prd_section = self._format_prd_section(prd_extraction)

        # Format code context
        code_section = self._format_code_section(code_context, language)

        # Build the prompt using string concatenation to avoid f-string brace issues
        prompt = "You are a software quality engineer tasked with generating code-level unit/integration tests."

        prompt += "\n\nGiven a Product Requirement Document (PRD) and the corresponding implementation, your task is to generate tests that verify the code logic fulfills the PRD specifications."

        prompt += "\n\n--- PRD REQUIREMENTS START ---"
        prompt += prd_section
        prompt += "\n--- PRD REQUIREMENTS END ---"

        prompt += "\n--- IMPLEMENTATION CODE CONTEXT START ---"
        prompt += code_section
        prompt += "\n--- IMPLEMENTATION CODE CONTEXT END ---"

        prompt += "\n\n### COMPARISON TASK ###\n\n"

        prompt += "Analyze the PRD requirements against the code context and identify any gaps or discrepancies. Then generate comprehensive unit/integration test cases in "
        prompt += language
        prompt += " that:\n\n"

        prompt += "1. Test that each functional specification from the PRD is implemented in the code\n"
        prompt += "2. Test each acceptance criterion with appropriate inputs and expected outputs\n"
        prompt += "3. Test edge cases and assumptions noted in the PRD\n"
        prompt += "4. Verify function signatures, class structures, and logic blocks match the expected behavior\n"
        prompt += "5. Cover both happy-path and error/edge cases\n\n"

        prompt += "Return STRICT JSON ONLY (no prose, no markdown formatting, no code blocks). The JSON must match the schema below exactly.\n\n"

        prompt += JSON_SCHEMA_PLACEHOLDER

        prompt += "\n\n### OUTPUT FORMAT EXAMPLE (PyTest for Python):\n\n"

        prompt += "```json\n"
        prompt += '{\n'
        prompt += '  "tests": [\n'
        prompt += '    {\n'
        prompt += '      "name": "test_calculate_total_happy_path",\n'
        prompt += '      "function": "calculate_total",\n'
        prompt += '      "inputs": {"items": [1, 2, 3]},\n'
        prompt += '      "expected": 6,\n'
        prompt += '      "description": "Calculate total of positive numbers",\n'
        prompt += '      "category": "functional"\n'
        prompt += '    },\n'
        prompt += '    {\n'
        prompt += '      "name": "test_calculate_total_empty_list",\n'
        prompt += '      "function": "calculate_total",\n'
        prompt += '      "inputs": {"items": []},\n'
        prompt += '      "expected": 0,\n'
        prompt += '      "description": "Calculate total of empty list",\n'
        prompt += '      "category": "edge_case"\n'
        prompt += '    }\n'
        prompt += '  ]\n'
        prompt += '}\n'
        prompt += "```\n\n"

        prompt += "### OUTPUT FORMAT EXAMPLE (Jest for JavaScript/TypeScript):\n\n"

        prompt += "```json\n"
        prompt += '{\n'
        prompt += '  "tests": [\n'
        prompt += '    {\n'
        prompt += '      "name": "calculateTotalHappyPath",\n'
        prompt += '      "function": "calculateTotal",\n'
        prompt += '      "inputs": {"items": [1, 2, 3]},\n'
        prompt += '      "expected": 6,\n'
        prompt += '      "description": "Calculate total of positive numbers",\n'
        prompt += '      "category": "functional"\n'
        prompt += '    }\n'
        prompt += '  ]\n'
        prompt += '}\n'
        prompt += "```\n\n"

        prompt += "Remember: Output JSON ONLY. No surrounding text, no markdown, no explanations."

        return prompt

        return prompt

    def _format_prd_section(self, prd: PRDExtraction) -> str:
        """Format the PRD extraction into a readable section."""
        lines = []
        lines.append(f"Requirement ID: {prd.requirement_id}")
        lines.append("")
        lines.append("Functional Specification:")
        lines.append(f"  {prd.functional_specification.specification}")
        if prd.functional_specification.category:
            lines.append(f"  Category: {prd.functional_specification.category}")
        if prd.functional_specification.complexity:
            lines.append(f"  Complexity: {prd.functional_specification.complexity}")
        lines.append("")
        lines.append("Acceptance Criteria:")
        if prd.acceptance_criteria:
            for i, ac in enumerate(prd.acceptance_criteria, 1):
                lines.append(f"  {i}. {ac.criterion}")
        else:
            lines.append("  (none specified)")
        lines.append("")
        lines.append("Edge Case Assumptions:")
        if prd.edge_case_assumptions:
            for i, eca in enumerate(prd.edge_case_assumptions, 1):
                lines.append(f"  {i}. Assumption: {eca.assumption}")
                if eca.context:
                    lines.append(f"     Context: {eca.context}")
                if eca.impact:
                    lines.append(f"     Impact: {eca.impact}")
        else:
            lines.append("  (none specified)")
        lines.append("")
        lines.append(f"Source Format: {prd.source_format}")
        return "\n".join(lines)

    def _format_code_section(
        self, code_ctx: structural_context_contextAST, language: str
    ) -> str:
        """Format the code structural context into a readable section."""
        lines = []
        lines.append(f"Filename: {code_ctx.filename}")
        lines.append("")

        # Imports
        lines.append("Imports:")
        for imp in code_ctx.imports:
            tag = ""
            if getattr(imp, "is_stdlib", False):
                tag = "[STDLIB]"
            elif getattr(imp, "is_local", False):
                tag = "[LOCAL]"
            elif getattr(imp, "is_third_party", False):
                tag = "[3RD-PTY]"
            lines.append(f"  {tag} {imp.module}" + (f" as {imp.alias}" if imp.alias else ""))
        lines.append("")

        # Classes
        lines.append("Classes:")
        for cls in code_ctx.classes:
            methods_info = []
            for m in cls.methods:
                args_str = ", ".join(m.args) if m.args else "()"
                returns_str = m.returns if m.returns else "void"
                doc = m.docstring if m.docstring else ""
                methods_info.append(
                    f"    - {m.name}{args_str} -> {returns_str}: {doc[:50] if doc else ''}"
                )
            doc = cls.docstring if cls.docstring else ""
            lines.append(
                f"  {cls.name}{': ' + doc[:50] if doc else ''}(line {cls.line})"
            )
            for method_line in methods_info:
                lines.append(method_line)
        lines.append("")

        # Functions (top-level)
        lines.append("Top-Level Functions:")
        for func in code_ctx.functions:
            args_str = ", ".join(func.args) if func.args else "()"
            returns_str = func.returns if func.returns else "None"
            doc = func.docstring if func.docstring else ""
            lines.append(
                f"  {func.name}{args_str} -> {returns_str}: {doc[:50] if doc else ''} (line {func.line})"
            )
        lines.append("")

        # Logic blocks
        lines.append("Logic Blocks:")
        if code_ctx.logic_blocks:
            for block in code_ctx.logic_blocks:
                cond = block.condition if block.condition else ""
                var = block.variable if block.variable else ""
                lines.append(
                    f"  {block.block_type} (line {block.line}): condition='{cond[:50]}' variable='{var}'"
                )
        else:
            lines.append("  (none detected)")
        lines.append("")

        # Docstrings summary
        lines.append("Docstrings:")
        for cls in code_ctx.classes:
            doc = cls.docstring if cls.docstring else ""
            if doc:
                lines.append(f"  {cls.name}: {doc[:80]}")
        for func in code_ctx.functions:
            doc = func.docstring if func.docstring else ""
            if doc:
                lines.append(f"  {func.name}: {doc[:80]}")

        return "\n".join(lines)

    def generate_pytest_tests(self, prd: PRDExtraction, code_ctx: structural_context_contextAST) -> Dict[str, Any]:
        """Generate PyTest test cases from PRD and code context.

        Args:
            prd: The PRD extraction with requirements.
            code_ctx: The structural context from code parsing.

        Returns:
            A dict with generated PyTest test cases.
        """
        prompt = self.build_comparison_prompt(prd, code_ctx, language="python")
        return {"prompt": prompt, "format": "pytest", "language": "python"}

    def generate_jest_tests(self, prd: PRDExtraction, code_ctx: structural_context_contextAST) -> Dict[str, Any]:
        """Generate Jest test cases from PRD and code context.

        Args:
            prd: The PRD extraction with requirements.
            code_ctx: The structural context from code parsing.

        Returns:
            A dict with generated Jest test cases.
        """
        prompt = self.build_comparison_prompt(prd, code_ctx, language="javascript")
        return {"prompt": prompt, "format": "jest", "language": "javascript"}

    def generate_all_tests(
        self, prd: PRDExtraction, code_ctx: structural_context_contextAST
    ) -> Dict[str, Any]:
        """Generate test cases in both PyTest and Jest formats.

        Args:
            prd: The PRD extraction with requirements.
            code_ctx: The structural context from code parsing.

        Returns:
            A dict with test cases for both formats.
        """
        return {
            "pytest": self.generate_pytest_tests(prd, code_ctx),
            "jest": self.generate_jest_tests(prd, code_ctx),
        }


def extract_structural_context_from_result(
    result: ASTExtractionResult,
) -> structural_context_contextAST:
    """Extract the structural context from an ASTExtractionResult.

    Args:
        result: The ASTExtractionResult from parsing Python source.

    Returns:
        The structural_context_contextAST.
    """
    if not result.success:
        raise ValueError(f"Failed to parse source: {result.error_message}")
    return result.structural_context


# Example usage
if __name__ == "__main__":
    # Sample PRD extraction
    from prd_parser.models import PRDExtraction, FunctionalSpecification

    sample_prd = PRDExtraction(
        requirement_id="REQ-001",
        functional_specification=FunctionalSpecification(
            specification="User can calculate the total of a list of numbers",
            category="mathematics",
            complexity="low",
        ),
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion="Given user provides a list of numbers, when user requests total, then correct sum is returned"
            ),
            AcceptanceCriterion(
                criterion="Given user provides an empty list, when user requests total, then zero is returned"
            ),
        ],
        edge_case_assumptions=[
            EdgeCaseAssumption(
                assumption="All items in the list are numeric",
                context="total calculation",
                impact="non-numeric items may cause errors",
            ),
        ],
        source_format="pdf",
    )

    # Sample code context (from ast_parser)
    sample_code = '''"""Sample module for demonstration."""

import os
import json


class MathUtils:
    """Utility functions for math operations."""

    PI = 3.14159

    def add(self, a: float, b: float) -> float:
        """Add two numbers."""
        return a + b


def calculate_total(items: list) -> float:
    """Calculate the total of a list of numbers."""
    return sum(items)


if __name__ == "__main__":
    print(calculate_total([1, 2, 3]))'''
    
    from prd_parser.ast_parser import extract_structural_context
    code_result = extract_structural_context(sample_code, "sample.py")
    code_ctx = extract_structural_context_from_result(code_result)

    # Build and use the prompt engine
    engine = CodeTestPromptEngine()

    # Generate prompt
    prompt_result = engine.generate_pytest_tests(sample_prd, code_ctx)
    print("=== PyTest Prompt ===")
    print(prompt_result["prompt"][:500], "...")