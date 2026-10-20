"""PDF and Markdown PRD parsers.

Handles ingestion of PRD documents in PDF and Markdown formats,
extracting raw text suitable for LLM-based feature/requirement extraction.
"""

import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import pdfplumber
    import pdfplumber.page
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False


class PRDParseResult:
    """Result of parsing a PRD document."""

    def __init__(
        self,
        text: str,
        source_format: str,
        pages: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.text = text.strip()
        self.source_format = source_format
        self.pages = pages
        self.metadata = metadata or {}
        self.word_count = len(self.text.split()) if self.text else 0

    def get_text_by_section(self, section_markers: List[str]) -> dict:
        """Extract text sections by marker keywords.

        Returns dict mapping marker -> list of text lines following that marker.
        """
        result = {}
        lines = self.text.split("\n")
        current_marker = None
        current_lines = []

        for line in lines:
            line_stripped = line.strip()
            # Check if this line starts a new section marker
            matched_marker = None
            for marker in section_markers:
                # Case-insensitive prefix match
                if line_stripped.lower().startswith(marker.lower()):
                    matched_marker = marker
                    break

            if matched_marker:
                # Save previous section
                if current_marker and current_lines:
                    result[current_marker] = current_lines
                current_marker = matched_marker
                current_lines = []
                # Remove the marker from the line content
                content = line_stripped[len(matched_marker):].strip()
                if content:
                    current_lines.append(content)
            elif current_marker:
                current_lines.append(line_stripped)
            else:
                # No section started yet, accumulate leading lines
                pass

        # Save last section
        if current_marker and current_lines:
            result[current_marker] = current_lines

        return result


class PDFPRDParser:
    """Parser for PDF-format PRD documents."""

    def __init__(self, *, extract_images: bool = False):
        self.extract_images = extract_images
        if not PDFPLUMBER_AVAILABLE:
            raise ImportError(
                "pdfplumber is required for PDF parsing. "
                "Install with: pip install pdfplumber"
            )

    def parse(self, file_path: str | Path) -> PRDParseResult:
        """Parse a PDF file and return extracted text.

        Args:
            file_path: Path to the PDF file.

        Returns:
            PRDParseResult containing the extracted text and metadata.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        return self.parse_bytes(file_path.read_bytes(), filename=file_path.name)

    def parse_bytes(
        self, content: bytes, filename: str = "uploaded.pdf"
    ) -> PRDParseResult:
        """Parse an in-memory PDF (e.g. an API upload).

        Args:
            content: Raw PDF bytes.
            filename: Original filename, used for metadata only.

        Returns:
            PRDParseResult containing the extracted text and metadata.
        """
        full_text: List[str] = []
        page_count = 0

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text.append(text)

        return PRDParseResult(
            text="\n".join(full_text),
            source_format="pdf",
            pages=page_count,
            metadata={
                "filename": filename,
                "total_pages": page_count,
                "file_size": len(content),
            },
        )


class MarkdownPRDParser:
    """Parser for Markdown-format PRD documents."""

    def parse(self, file_path: str | Path) -> PRDParseResult:
        """Parse a Markdown file and return extracted text.

        Args:
            file_path: Path to the Markdown file.

        Returns:
            PRDParseResult containing the extracted text and metadata.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Markdown file not found: {file_path}")

        result = self.parse_bytes(file_path.read_bytes(), filename=file_path.name)
        result.metadata["file_size"] = file_path.stat().st_size
        return result

    def parse_bytes(
        self, content: bytes, filename: str = "uploaded.md"
    ) -> PRDParseResult:
        """Parse an in-memory Markdown document (e.g. an API upload)."""
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("utf-8", errors="replace")
        return self.parse_text(text, filename=filename, file_size=len(content))

    def parse_text(
        self, text: str, *, filename: str = "", file_size: int = 0
    ) -> PRDParseResult:
        """Parse Markdown text while preserving line and section structure."""
        # Remove fenced code blocks (``` ... ```) for cleaner LLM input
        text = re.sub(r"```[\s\S]*?```", "", text)
        # Remove inline code backticks but keep the content
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)

        # Normalise horizontal whitespace only. Newlines are meaningful:
        # acceptance criteria and edge-case sections are line based.
        cleaned_lines = []
        for line in text.splitlines():
            line = line.replace("\t", " ").rstrip()
            line = re.sub(r"[ ]{2,}", " ", line)
            cleaned_lines.append(line)

        cleaned = "\n".join(cleaned_lines)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

        # Count headings as a rough page estimate
        heading_count = len(re.findall(r"^#{1,6}\s", cleaned, re.MULTILINE))

        return PRDParseResult(
            text=cleaned,
            source_format="markdown",
            pages=heading_count,  # rough estimate
            metadata={
                "filename": filename,
                "heading_count": heading_count,
                "file_size": file_size,
            },
        )