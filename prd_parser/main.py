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

    # From Python file or directory
    from prd_parser import parse_python_file, parse_python_directory
    result = parse_python_file("path/to/module.py")
    result = parse_python_directory("path/to/repo")
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional, Union

from prd_parser.extractor import Extractor
from prd_parser.models import PRDExtraction, PRD_EXTRACTION_SCHEMA
from prd_parser.parsers import MarkdownPRDParser, PDFPRDParser
from prd_parser.ast_parser import extract_structural_context, ASTParser

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
                f"{len(result.structural_context.functions)} functions, "
                f"{len(result.structural_context.logic_blocks)} logic blocks"
            )
        return result
    except Exception as e:
        logger.error(f"Failed to parse Python source '{filename}': {e}")
        return ASTExtractionResult(
            structural_context=None,  # type: ignore[arg-type]
            success=False,
            error_message=str(e),
        )


def parse_python_file(
    file_path: Union[str, Path],
) -> ASTExtractionResult:
    """Extract structural context from a Python file.

    Args:
        file_path: Path to the Python file to parse.

    Returns:
        ASTExtractionResult containing the extracted structural context.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Python file not found: {file_path}")
    if file_path.suffix != ".py":
        raise ValueError(f"Not a Python file: {file_path}")

    try:
        source = file_path.read_text(encoding="utf-8")
        return extract_structural_context(source, str(file_path))
    except Exception as e:
        logger.error(f"Failed to parse Python file '{file_path}': {e}")
        return ASTExtractionResult(
            structural_context=None,  # type: ignore[arg-type]
            success=False,
            error_message=str(e),
        )


def parse_python_directory(
    dir_path: Union[str, Path],
    *, recursive: bool = True,
    include_pattern: str = "*.py",
) -> List[ASTExtractionResult]:
    """Extract structural context from all Python files in a directory.

    Args:
        dir_path: Path to the directory to parse.
        recursive: Whether to search recursively.
        include_pattern: Glob pattern for file inclusion.

    Returns:
        List of ASTExtractionResult, one per parsed file.
    """
    dir_path = Path(dir_path)
    if not dir_path.exists():
        raise FileNotFoundError(f"Directory not found: {dir_path}")
    if not dir_path.is_dir():
        raise ValueError(f"Not a directory: {dir_path}")

    results: List[ASTExtractionResult] = []
    search_pattern = include_pattern if "*" in include_pattern else f"**/{include_pattern}"

    files = list(dir_path.rglob("*.py")) if recursive else list(dir_path.glob("*.py"))

    for file_path in sorted(files):
        try:
            result = parse_python_file(file_path)
            if result.success:
                results.append(result)
        except Exception as e:
            logger.warning(f"Failed to parse {file_path}: {e}")

    return results


def parse_python_file_list(
    file_paths: List[Union[str, Path]],
) -> List[ASTExtractionResult]:
    """Extract structural context from a list of Python files.

    Args:
        file_paths: List of paths to Python files to parse.

    Returns:
        List of ASTExtractionResult, one per parsed file.
    """
    results: List[ASTExtractionResult] = []
    for file_path in file_paths:
        try:
            result = parse_python_file(file_path)
            if result.success:
                results.append(result)
        except Exception as e:
            logger.warning(f"Failed to parse {file_path}: {e}")
    return results


# Example CLI usage when run directly
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python main.py <python_file_or_directory> [options]")
        print("  <python_file_or_directory>: Path to Python file or directory to parse")
        print("  --recursive / -r: Recursive directory search (default: True)")
        print("  --pattern / -p: Glob pattern for file inclusion (default: *.py)")
        sys.exit(1)

    target = sys.argv[1]
    recursive = "--no-recursive" not in sys.argv and "-r" not in sys.argv
    pattern = "*.py"

    # Parse remaining arguments
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] in ("--recursive", "-r"):
            recursive = True
        elif args[i] in ("--no-recursive"):
            recursive = False
        elif args[i] in ("--pattern", "-p") and i + 1 < len(args):
            pattern = args[i + 1]
            i += 1
        i += 1

    target_path = Path(target)

    if target_path.is_file():
        if target_path.suffix == ".py":
            result = parse_python_file(target)
            if result.success:
                ctx = result.structural_context
                print(f"Filename: {ctx.filename}")
                print(f"\nImports ({len(ctx.imports)}):")
                for imp in ctx.imports:
                    tag = ""
                    if imp.is_stdlib:
                        tag = "[STDLIB]"
                    elif imp.is_local:
                        tag = "[LOCAL]"
                    elif imp.is_third_party:
                        tag = "[3RD-PTY]"
                    print(f"  {tag} {imp.module}" + (f" as {imp.alias}" if imp.alias else ""))
                print(f"\nClasses ({len(ctx.classes)}):")
                for cls in ctx.classes:
                    print(f"  {cls.name} (line {cls.line})")
                    print(f"    Bases: {cls.bases}")
                    print(f"    Methods: {[m.name for m in cls.methods]}")
                    print(f"    Docstring: {cls.docstring[:60] if cls.docstring else 'None'}...")
                print(f"\nFunctions ({len(ctx.functions)}):")
                for func in ctx.functions:
                    print(f"  {func.name} (line {func.line})" + (f" async" if func.is_async else ""))
                    if func.args:
                        print(f"    Args: {func.args}")
                    if func.returns:
                        print(f"    Returns: {func.returns}")
                    print(f"    Docstring: {func.docstring[:60] if func.docstring else 'None'}...")
                print(f"\nLogic Blocks ({len(ctx.logic_blocks)}):")
                for block in ctx.logic_blocks:
                    print(f"  {block.block_type} (line {block.line})")
                    print(f"    Condition: {block.condition[:60] if block.condition else 'None'}...")
                    print(f"    Variable: {block.variable if block.variable else 'None'}...")
            else:
                print(f"Error: {result.error_message}")
        else:
            print(f"Error: Not a Python file: {target}")
    elif target_path.is_dir():
        results = parse_python_directory(target, recursive=recursive, include_pattern=pattern)
        print(f"Parsed {len(results)} Python file(s) from {target}")
        for result in results:
            if result.success:
                ctx = result.structural_context
                print(f"\n--- {ctx.filename} ---")
                print(f"Functions: {[f.name for f in ctx.functions]}")
                print(f"Classes: {[c.name for c in ctx.classes]}")
                print(f"Logic blocks: {[b.block_type for b in ctx.logic_blocks]}")
    else:
        print(f"Error: Path not found: {target}")