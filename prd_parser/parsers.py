"""PDF and Markdown PRD parsers.

Handles ingestion of PRD documents in PDF and Markdown formats,
extracting raw text suitable for LLM-based feature/requirement extraction.
"""

import re
from pathlib import Path
from typing import List, Optional

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

        full_text = []
        page_count = 0

        with pdfplumber.open(file_path) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text.append(text)

        combined_text = "\n".join(full_text)
        metadata = {
            "total_pages": page_count,
            "file_size": file_path.stat().st_size if file_path.exists() else 0,
        }

        return PRDParseResult(
            text=combined_text,
            source_format="pdf",
            pages=page_count,
            metadata=metadata,
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

        # Read the file content
        text = file_path.read_text(encoding="utf-8")

        # Basic Markdown cleanup - remove code blocks for cleaner LLM input
        # Remove fenced code blocks (``` ... ```)
        text = re.sub(r"```[\s\S]*?```", "", text)
        # Remove inline code (`code`)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        # Remove HTML tags
        text = re.sub(r"<.*?>", " ", text)
        # Collapse multiple whitespaces
        text = re.sub(r"\s+", " ", text)

        # Try to count headings as rough page estimate
        heading_count = len(re.findall(r"^#{1,6}\s", text, re.MULTILINE))

        metadata = {
            "heading_count": heading_count,
            "file_size": file_path.stat().st_size if file_path.exists() else 0,
        }

        return PRDParseResult(
            text=text,
            source_format="markdown",
            pages=heading_count,  # rough estimate
            metadata=metadata,
        )