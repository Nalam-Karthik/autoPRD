"""Main PRD parsing module — public API entry point.

Usage:
    from prd_parser import parse_prd_from_file, parse_prd_from_text

    # From file (PDF or Markdown)
    result = parse_prd_from_file("path/to/prd.pdf")
    print(result.requirement_id)
    print(result.functional_specification.specification)

    # From text directly
    result = parse_prd_from_text(prd_text, source_format="markdown")

    # From Python source code (AST-based structural extraction)
    from prd_parser import parse_python_from_source
    result = parse_python_from_source(sample_python_code)
    print(result.structural_context.imports)
    print(result.structural_context.classes)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from prd_parser.extractor import Extractor
from prd_parser.models import PRDExtraction, PRD_EXTRACTION_SCHEMA
from prd_parser.parsers import MarkdownPRDParser, PDFPRDParser
from prd_parser.ast_parser import extract_structural_context

logger = logging.getLogger(__name__)


# Singleton extractor instance — lazy-initialized
_extractor: Optional[Extractor] = None


def _get_extractor() -> Extractor:
    """Return a singleton Extractor instance (lazy init)."""
    global _extractor
    if _extractor is None:
        _extractor = Extractor(model_name="gpt-4o-mini")
    return _extractor


def parse_prd_from_file(
    file_path: str | Path,
    *,
    llm_client=None,
    model_name: str = "gpt-4o-mini",
) -> PRDExtraction:
    """Parse a PRD from a file (PDF or Markdown).

    Automatically detects the format based on file extension.

    Args:
        file_path: Path to the PRD file (.pdf or .md).
        llm_client: Optional LLM client instance. If not provided, uses
            the default model specified at initialization.
        model_name: LLM model name to use for extraction.

    Returns:
        PRDExtraction instance with all extracted fields.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"PRD file not found: {file_path}")

    # Detect format from extension
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        # Parse PDF
        pdf_parser = PDFPRDParser()
        parse_result = pdf_parser.parse(file_path)
    elif ext in (".md", ".markdown"):
        # Parse Markdown
        md_parser = MarkdownPRDParser()
        parse_result = md_parser.parse(file_path)
    else:
        raise ValueError(
            f"Unsupported file format: {ext}. "
            "Supported formats: .pdf, .md, .markdown"
        )

    # Extract structured data using LLM
    extractor = _get_extractor() if _extractor else Extractor(model_name=model_name)
    extraction = extractor.extract(prd_text=parse_result.text, source_format=parse_result.source_format)

    # Also validate against standalone JSON schema for extra safety
    try:
        extraction.validate_json_schema(extraction.to_json())
    except ValueError as e:
        logger.warning(f"Schema validation warning: {e}")

    return extraction


def parse_prd_from_text(
    prd_text: str,
    *,
    source_format: str = "pdf",
    llm_client=None,
    model_name: str = "gpt-4o-mini",
) -> PRDExtraction:
    """Parse PRD from raw text string.

    Args:
        prd_text: The full text content of the PRD.
        source_format: "pdf" or "markdown" — indicates the original format.
        llm_client: Optional LLM client instance.
        model_name: LLM model name to use for extraction.

    Returns:
        PRDExtraction instance with all extracted fields.
    """
    extractor = _get_extractor() if _extractor else Extractor(model_name=model_name)
    extraction = extractor.extract(prd_text=prd_text, source_format=source_format)

    # Validate against standalone JSON schema
    try:
        extraction.validate_json_schema(extraction.to_json())
    except ValueError as e:
        logger.warning(f"Schema validation warning: {e}")

    return extraction


def validate_prd_json(json_data: dict) -> PRDExtraction:
    """Validate a raw dict against the PRD extraction schema.

    Args:
        json_data: The dict to validate.

    Returns:
        PRDExtraction instance if valid.

    Raises:
        ValueError: If the data does not conform to the expected schema.
    """
    # First validate with Pydantic
    extraction = PRDExtraction.model_validate(json_data)

    # Then validate with standalone JSON Schema
    extraction.validate_json_schema(extraction.to_json())

    return extraction


def parse_python_from_source(
    source: str,
    filename: str = "<string>",
) -> ASTExtractionResult:
    """Extract structural context from Python source code using AST parsing.

    Args:
        source: Python source code as a string.
        filename: Name of the file being parsed (for error reporting).

    Returns:
        ASTExtractionResult containing the extracted structural context
        including imports, classes, functions, and their relationships.
    """
    try:
        result = extract_structural_context(source, filename)
        if result.success:
            logger.info(
                f"Successfully parsed Python source '{filename}': "
                f"{len(result.structural_context.imports)} imports, "
                f"{len(result.structural_context.classes)} classes, "
                f"{len(result.structural_context.functions)} functions"
            )
        return result
    except Exception as e:
        logger.error(f"Failed to parse Python source '{filename}': {e}")
        return ASTExtractionResult(
            structural_context=None,  # type: ignore[arg-type]
            success=False,
            error_message=str(e),
        )