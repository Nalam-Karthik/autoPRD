"""FastAPI application for the PRD-to-Code test generation pipeline.

Exposes endpoints:
- GET  /: Serve the autoPRD upload UI
- POST /parse-prd: Parse PRD text (Markdown or extracted PDF text)
- POST /upload-file: Upload one or more PRD files (PDF/Markdown)
- POST /generate-functional-tests: Generate functional test prompts
- POST /validate-code: Validate generated tests against PRD acceptance criteria
- GET  /health: Health check
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from prd_parser.ast_parser import extract_structural_context, structural_context_context
from prd_parser.code_test_generator import CodeTestPromptEngine
from prd_parser.extractor import Extractor
from prd_parser.models import (
    AcceptanceCriterion,
    EdgeCaseAssumption,
    FunctionalSpecification,
    PRDExtraction,
)
from prd_parser.parsers import MarkdownPRDParser, PDFPRDParser
from prd_parser.verifier import verify

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("prd-api")
logger.setLevel(logging.INFO)
if not logger.handlers:
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

    prd_text: str = Field(
        ...,
        description="Raw PRD text (Markdown, or text extracted from a PDF).",
        min_length=1,
    )
    source_format: str = Field(
        default="markdown",
        description="Input format: 'pdf' or 'markdown'.",
    )
    use_llm: bool = Field(
        default=True,
        description=(
            "Try LLM-based extraction first. Falls back to the built-in "
            "deterministic parser when no LLM credentials are configured."
        ),
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
    code_source: str = Field(..., description="Source code to analyze")
    language: str = Field(
        default="python",
        description="Programming language: python or javascript/typescript",
    )


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
        description=(
            "Structural context from code parsing "
            "(imports, functions, classes, logic blocks)"
        ),
    )


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PRD-to-Code Test Generation Pipeline",
    version="0.1.0",
    description=(
        "API for parsing PRDs, generating code-level functional tests "
        "(PyTest/Jest), and validating code compliance against PRD requirements."
    ),
)

# The UI may be served from the API itself, a local static server, or file://.
_cors_origins = [
    origin.strip()
    for origin in os.getenv("AUTOPRD_CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

INDEX_HTML = Path(__file__).resolve().parent.parent / "index.html"


# ---------------------------------------------------------------------------
# PRD text extraction helpers
# ---------------------------------------------------------------------------

def _clean_markdown_line(line: str) -> str:
    """Remove common Markdown decoration from a single line."""
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = re.sub(r"^(?:[-*+]|\d+[.)])\s+", "", line)
    line = line.replace("**", "").replace("__", "")
    return line.strip()


def _extract_functional_spec(text: str) -> str:
    """Extract the primary functional specification from PRD text."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # Prefer an explicit "Functional Specification" section.
    for index, line in enumerate(lines):
        if re.match(
            r"^#{0,6}\s*functional\s+specification\b",
            line.strip(),
            re.IGNORECASE,
        ):
            for following in lines[index + 1 :]:
                candidate = _clean_markdown_line(following)
                if candidate and not following.strip().startswith("#"):
                    return candidate[:200]

    # Otherwise use the first meaningful line that is not a heading,
    # requirement ID, or acceptance criterion.
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        requirement_line = re.match(
            r"^REQ[-_ ]?\d{3,}\b\s*[:\-\u2013]?\s*(.*)$",
            stripped,
            re.IGNORECASE,
        )
        if requirement_line:
            remainder = requirement_line.group(1).strip()
            if remainder:
                return _clean_markdown_line(remainder)[:200]
            continue

        if re.match(r"^(?:[-*+]|\d+[.)])\s+", stripped):
            continue

        return _clean_markdown_line(stripped)[:200]

    return ""


def _extract_acceptance_criteria(text: str) -> List[str]:
    """Extract numbered/bulleted acceptance criteria, preserving line structure."""
    criteria: List[str] = []
    seen: set[str] = set()
    in_acceptance_section = False

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()

        heading = re.match(r"^#{1,6}\s+(.*)$", stripped)
        if heading:
            title = heading.group(1).lower()
            if "acceptance" in title and ("criteria" in title or "criterion" in title):
                in_acceptance_section = True
            elif in_acceptance_section:
                in_acceptance_section = False
            continue

        item = re.match(r"^(?:\d+[.)]|[-*+])\s+(.*)$", stripped)
        if not item:
            continue

        content = _clean_markdown_line(item.group(1))
        if not content:
            continue

        starts_with_bdd_keyword = content.startswith(("Given ", "When ", "Then "))
        if (in_acceptance_section or starts_with_bdd_keyword) and content not in seen:
            criteria.append(content)
            seen.add(content)

    return criteria


def _extract_edge_case_assumptions(text: str) -> List[Dict[str, str]]:
    """Extract edge-case assumptions from a dedicated PRD section."""
    assumptions: List[Dict[str, str]] = []
    seen: set[str] = set()
    in_edge_section = False

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()

        heading = re.match(r"^#{1,6}\s+(.*)$", stripped)
        if heading:
            title = heading.group(1)
            if re.search(r"edge[\s_-]*case|assumption", title, re.IGNORECASE):
                in_edge_section = True
            elif in_edge_section:
                in_edge_section = False
            continue

        if not in_edge_section or not stripped:
            continue

        content = _clean_markdown_line(stripped)
        if content and content not in seen:
            assumptions.append(
                {"assumption": content, "context": "", "impact": ""}
            )
            seen.add(content)

    return assumptions


def _parse_prd_text(prd_text: str, source_format: str = "markdown") -> Dict[str, Any]:
    """Deterministically parse PRD text into a structured dict."""
    text = prd_text or ""

    requirement_id = "REQ-001"
    match = re.search(r"\bREQ[-_ ]?(\d{3,})\b", text, re.IGNORECASE)
    if match:
        requirement_id = f"REQ-{match.group(1)}"

    return {
        "requirement_id": requirement_id,
        "functional_specification": _extract_functional_spec(text),
        "acceptance_criteria": _extract_acceptance_criteria(text),
        "edge_case_assumptions": _extract_edge_case_assumptions(text),
        "source_format": source_format,
    }


def _extraction_to_dict(extraction: PRDExtraction) -> Dict[str, Any]:
    """Convert a PRDExtraction model into the API response shape."""
    return {
        "requirement_id": extraction.requirement_id,
        "functional_specification": extraction.functional_specification.specification,
        "acceptance_criteria": [
            criterion.criterion for criterion in extraction.acceptance_criteria
        ],
        "edge_case_assumptions": [
            {
                "assumption": assumption.assumption,
                "context": assumption.context or "",
                "impact": assumption.impact or "",
            }
            for assumption in extraction.edge_case_assumptions
        ],
        "source_format": extraction.source_format,
    }


def _parse_prd_with_fallback(
    prd_text: str, source_format: str, use_llm: bool
) -> tuple[Dict[str, Any], str]:
    """Parse with the LLM when available, otherwise use the heuristic parser."""
    if use_llm and prd_text.strip():
        try:
            extraction = Extractor().extract(prd_text, source_format)
            return _extraction_to_dict(extraction), "llm"
        except Exception as exc:
            logger.warning(
                "LLM extraction unavailable; using deterministic parser: %s", exc
            )

    return _parse_prd_text(prd_text, source_format), "heuristic"


# ---------------------------------------------------------------------------
# Code/test helpers
# ---------------------------------------------------------------------------

def _generate_tests(
    prd_dict: Dict[str, Any], code_source: str, language: str = "python"
) -> Dict[str, Any]:
    """Generate functional test prompts from PRD data and code context."""
    normalised_language = language.strip().lower()
    if normalised_language in ("javascript", "js", "typescript", "ts"):
        prompt_language = "javascript"
        filename = "implementation.js"
    elif normalised_language == "python":
        prompt_language = "python"
        filename = "implementation.py"
    else:
        raise ValueError(
            f"Unsupported language: {language!r}. Use 'python' or 'javascript'."
        )

    if prompt_language == "python":
        code_result = extract_structural_context(code_source, filename)
        if not code_result.success:
            raise ValueError(code_result.error_message or "Could not parse code.")
        code_ctx = code_result.structural_context
    else:
        # No JS/TS AST parser is bundled; pass the source through to the prompt.
        code_ctx = structural_context_context(
            filename=filename, raw_source=code_source
        )

    parsed_prd = PRDExtraction(
        requirement_id=prd_dict.get("requirement_id", "REQ-001"),
        functional_specification=FunctionalSpecification(
            specification=prd_dict.get("functional_specification") or "User functionality",
            category=prd_dict.get("category") or None,
            complexity=prd_dict.get("complexity") or None,
        ),
        acceptance_criteria=[
            AcceptanceCriterion(criterion=criterion)
            for criterion in prd_dict.get("acceptance_criteria", [])
        ],
        edge_case_assumptions=[
            EdgeCaseAssumption(
                assumption=assumption.get("assumption", ""),
                context=assumption.get("context") or None,
                impact=assumption.get("impact") or None,
            )
            for assumption in prd_dict.get("edge_case_assumptions", [])
            if assumption.get("assumption")
        ],
        source_format=prd_dict.get("source_format", "markdown"),
    )

    engine = CodeTestPromptEngine()
    if prompt_language == "python":
        prompt_result = engine.generate_pytest_tests(parsed_prd, code_ctx)
    else:
        prompt_result = engine.generate_jest_tests(parsed_prd, code_ctx)

    return {
        "prompt": prompt_result["prompt"],
        "format": prompt_result["format"],
        "language": prompt_result["language"],
        "code_context": {
            "filename": code_ctx.filename,
            "functions": [function.name for function in code_ctx.functions],
            "classes": [cls.name for cls in code_ctx.classes],
            "logic_blocks": [
                block.block_type for block in code_ctx.logic_blocks
            ],
        },
    }


def _validate_code(
    prd_dict: Dict[str, Any], code_ctx_dict: Dict[str, Any]
) -> Dict[str, Any]:
    """Validate generated tests against PRD requirements."""
    parsed_prd = PRDExtraction(
        requirement_id=prd_dict.get("requirement_id", "REQ-001"),
        functional_specification=FunctionalSpecification(
            specification=prd_dict.get("functional_specification") or "User functionality"
        ),
        acceptance_criteria=[
            AcceptanceCriterion(criterion=criterion)
            for criterion in prd_dict.get("acceptance_criteria", [])
        ],
        edge_case_assumptions=[
            EdgeCaseAssumption(
                assumption=assumption.get("assumption", ""),
                context=assumption.get("context") or None,
                impact=assumption.get("impact") or None,
            )
            for assumption in prd_dict.get("edge_case_assumptions", [])
            if assumption.get("assumption")
        ],
        source_format=prd_dict.get("source_format", "markdown"),
    )

    return verify(parsed_prd, prd_dict.get("generated_tests", {}), code_ctx_dict)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_ui() -> FileResponse:
    """Serve the autoPRD upload UI when it is present next to the package."""
    if not INDEX_HTML.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(INDEX_HTML)


@app.post("/parse-prd", summary="Parse PRD text")
async def parse_prd_endpoint(
    request: ParsePRDRequest = Body(...),
) -> Dict[str, Any]:
    """Parse PRD text and extract structured requirements."""
    if request.source_format not in ("pdf", "markdown"):
        raise HTTPException(
            status_code=400,
            detail="source_format must be 'pdf' or 'markdown'",
        )

    result, method = _parse_prd_with_fallback(
        request.prd_text, request.source_format, request.use_llm
    )
    result["extraction_method"] = method
    return result


@app.post(
    "/generate-functional-tests",
    summary="Generate functional test prompts from PRD and code context",
)
async def generate_functional_tests_endpoint(
    request: GenerateTestsRequest = Body(...),
) -> Dict[str, Any]:
    """Combine PRD requirements with code context to build a test prompt."""
    prd_dict = {
        "requirement_id": request.prd_requirement_id,
        "functional_specification": request.prd_functional_spec,
        "acceptance_criteria": request.prd_acceptance_criteria,
        "edge_case_assumptions": request.prd_edge_case_assumptions,
        "source_format": "markdown",
    }

    try:
        return _generate_tests(prd_dict, request.code_source, request.language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/validate-code",
    summary="Validate generated tests against PRD requirements",
)
async def validate_code_endpoint(
    request: ValidateCodeRequest = Body(...),
) -> JSONResponse:
    """Validate tests and return coverage, gaps, discrepancies, recommendations."""
    prd_dict = {
        "requirement_id": request.prd_requirement_id,
        "functional_specification": request.prd_functional_spec,
        "acceptance_criteria": request.prd_acceptance_criteria,
        "edge_case_assumptions": request.prd_edge_case_assumptions,
        "generated_tests": request.generated_tests,
        "source_format": "markdown",
    }

    try:
        result = _validate_code(prd_dict, request.code_structural_context)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(content=result)


@app.post("/upload-file", summary="Upload one or more PRD files (PDF or Markdown)")
async def upload_file_endpoint(
    file: List[UploadFile] = File(...),
) -> JSONResponse:
    """Parse uploaded PRD files and return structured requirements per file."""
    results: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for upload in file:
        filename = upload.filename or "uploaded.prd"
        extension = Path(filename).suffix.lower()
        content = await upload.read()

        if not content:
            errors.append({"filename": filename, "error": "File is empty."})
            continue

        try:
            if extension == ".pdf":
                parsed = PDFPRDParser().parse_bytes(content, filename)
            elif extension in (".md", ".markdown"):
                parsed = MarkdownPRDParser().parse_bytes(content, filename)
            else:
                errors.append(
                    {
                        "filename": filename,
                        "error": (
                            f"Unsupported file format: {extension or '(none)'}. "
                            "Supported formats: .pdf, .md, .markdown"
                        ),
                    }
                )
                continue
        except Exception as exc:
            logger.warning("Failed to parse uploaded file %s: %s", filename, exc)
            errors.append({"filename": filename, "error": str(exc)})
            continue

        if not parsed.text.strip():
            errors.append(
                {
                    "filename": filename,
                    "error": "No extractable text found in the document.",
                }
            )
            continue

        parsed_fields = _parse_prd_text(parsed.text, parsed.source_format)
        results.append(
            {
                **parsed_fields,
                "filename": filename,
                "word_count": parsed.word_count,
            }
        )

    payload = {
        "processed": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }
    status_code = 200 if results else 400
    return JSONResponse(content=payload, status_code=status_code)


@app.get("/health", summary="Health check")
async def health_check() -> Dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok", "message": "PRD-to-Code API is running"}
