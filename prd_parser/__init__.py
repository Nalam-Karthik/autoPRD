"""autoPRD — generate code-level tests from Product Requirement Documents.

Public entry points:
    parse_prd_from_file, parse_prd_from_text, validate_prd_json,
    parse_python_from_source, parse_python_file, parse_python_directory,
    extract_structural_context, CodeTestPromptEngine, verify.
"""

from prd_parser.ast_parser import (
    ASTExtractionResult,
    ASTParser,
    extract_structural_context,
)
from prd_parser.code_test_generator import (
    CodeTestPromptEngine,
    extract_structural_context_from_result,
)
from prd_parser.main import (
    parse_prd_from_file,
    parse_prd_from_text,
    parse_python_directory,
    parse_python_file,
    parse_python_file_list,
    parse_python_from_source,
    validate_prd_json,
)
from prd_parser.models import (
    AcceptanceCriterion,
    EdgeCaseAssumption,
    FunctionalSpecification,
    PRD_EXTRACTION_SCHEMA,
    PRDExtraction,
)
from prd_parser.verifier import quick_verify, verify

__version__ = "0.1.0"

__all__ = [
    "ASTExtractionResult",
    "ASTParser",
    "AcceptanceCriterion",
    "CodeTestPromptEngine",
    "EdgeCaseAssumption",
    "FunctionalSpecification",
    "PRD_EXTRACTION_SCHEMA",
    "PRDExtraction",
    "extract_structural_context",
    "extract_structural_context_from_result",
    "parse_prd_from_file",
    "parse_prd_from_text",
    "parse_python_directory",
    "parse_python_file",
    "parse_python_file_list",
    "parse_python_from_source",
    "quick_verify",
    "validate_prd_json",
    "verify",
]
