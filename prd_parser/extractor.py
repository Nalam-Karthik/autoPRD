"""LLM-based PRD feature/requirement extractor.

Uses an LLM (OpenAI-compatible) to extract structured data from parsed PRD
text. Output is validated against PRD_EXTRACTION_SCHEMA.
"""

import json
import logging
from typing import Optional

from prd_parser.models import PRDExtraction, PRD_EXTRACTION_SCHEMA

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extraction prompt template
# ---------------------------------------------------------------------------
EXTRACTION_PROMPT = """You are an AI assistant tasked with extracting structured requirements from a Product Requirement Document (PRD).

Extract the following fields from the PRD text below. Be precise and only extract what is explicitly stated — do not infer, expand, or hallucinate.

Return STRICT JSON ONLY (no prose, no markdown formatting, no code blocks). The JSON must be valid and match the schema defined below.

--- PRD TEXT START ---
{prd_text}
--- PRD TEXT END ---

--- EXTRACTION INSTRUCTIONS ---

1. requirement_id:
   - Extract the requirement ID if present (format: REQ-NNN where NNN is 3+ digits).
   - If multiple IDs are found, pick the first one that appears.
   - If no ID is found, use "UNKNOWN-REQ".
   - Do NOT generate a new ID — only extract existing ones.

2. functional_specification:
   - Extract the core functional specification / description of what the system should do.
   - Use the exact wording from the PRD when possible.
   - If multiple specifications exist, pick the primary/main one.
   - Keep it concise (1-2 sentences maximum).
   - If truly not found, use an empty string "", but try your best to find something.

3. acceptance_criteria:
   - Extract individual acceptance criteria statements.
   - Each criterion should be a concise, testable statement.
   - Format each as plain text — do NOT include JSON escaping artifacts.
   - If no explicit acceptance criteria are found, use an empty array [].
   - Maximum 10 criteria — prioritize the most important ones.

4. edge_case_assumptions:
   - Extract any edge-case assumptions, conditions, or constraints noted in the PRD.
   - These are implicit assumptions that, if violated, could cause unexpected behavior.
   - If none are found, use an empty array [].
   - Maximum 5 assumptions.

5. source_format:
   - Set this to "pdf" or "markdown" based on the input document type.
   - This is provided to you as context; use the value that matches the actual source.

<JSON_SCHEMA_PLACEHOLDER>--- OUTPUT FORMAT ---

{
  "requirement_id": "REQ-XXX",
  "functional_specification": {
    "specification": "The system shall...",
    "category": null,
    "complexity": null
  },
  "acceptance_criteria": [
    {"criterion": "Given X, when Y, then Z"},
    ...
  ],
  "edge_case_assumptions": [
    {"assumption": "If X, then assume Y"},
    ...
  ],
  "source_format": "pdf"
}

Remember: Output JSON ONLY. No surrounding text, no markdown, no explanations.
"""


class Extractor:
    """Extracts structured requirement data from parsed PRD text using an LLM."""

    def __init__(self, *, llm_client=None, model_name: str = "gpt-4o-mini"):
        """Initialize the extractor.

        Args:
            llm_client: An LLM client object with a `chat.completions.create`
                method (e.g., OpenAI client). If None, a basic placeholder is set.
            model_name: Name of the LLM model to use.
        """
        self.llm_client = llm_client
        self.model_name = model_name

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM and return the raw response text.

        Subclasses or concrete implementations should override this method
        with actual LLM API calls.
        """
        if self.llm_client is None:
            raise NotImplementedError(
                "LLM client not configured. Pass an OpenAI-compatible client "
                "instance when initializing Extractor."
            )
        # Default implementation - should be overridden
        raise NotImplementedError("Subclasses must implement _call_llm")

    def extract(self, prd_text: str, source_format: str = "pdf") -> PRDExtraction:
        """Extract structured data from PRD text.

        Args:
            prd_text: The full text content of the PRD.
            source_format: "pdf" or "markdown" — passed through to the output.

        Returns:
            PRDExtraction model instance with the extracted data.
        """
        # Format the prompt with the actual PRD text
        # Safely insert prd_text into the prompt.
        # using str.replace() to avoid Python .format() clashing
        formatted_prompt = EXTRACTION_PROMPT.replace("{prd_text}", prd_text)
        # Call the LLM
        raw_response = self._call_llm(formatted_prompt)

        # Clean up the response — strip markdown code fences if present
        raw_response = self._clean_llm_response(raw_response)

        # Parse the JSON response
        try:
            data = json.loads(raw_response)
        except json.JSONDecodeError as e:
            logger.error(f"LLM response was not valid JSON: {raw_response[:200]}")
            raise ValueError(f"LLM did not return valid JSON: {e}")

        # Validate against the expected schema and construct the Pydantic model
        try:
            validated = PRDExtraction.model_validate(data)
        except Exception as e:
            logger.error(f"Validation failed against PRDExtraction model: {e}")
            logger.debug(f"Parsed data: {data}")
            raise ValueError(f"Extracted data failed schema validation: {e}")

        # Update source_format if needed (in case it was different)
        if validated.source_format != source_format:
            validated = validated.model_copy(
                update={"source_format": source_format}
            )

        return validated

    @staticmethod
    def _clean_llm_response(text: str) -> str:
        """Clean up the LLM response to extract pure JSON.

        Removes markdown fences, triple-backticks, and any surrounding prose.
        """
        # Remove triple-backtick code blocks (with or without language specifier)
        cleaned = re.sub(r"^```[\w]*\n", "", text, flags=re.MULTILINE)
        cleaned = re.sub(r"\n```$", "", cleaned, flags=re.MULTILINE)
        # Remove triple-backtick code blocks (no language)
        cleaned = re.sub(r"^```\n", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\n```$", "", cleaned, flags=re.MULTILINE)
        # Strip leading/trailing whitespace and prose markers
        cleaned = cleaned.strip()
        # Remove any trailing comma before final brace if present
        cleaned = cleaned.rstrip(",")
        return cleaned

    def validate_json_schema(self, json_data: dict) -> bool:
        """Validate raw dict against the standalone JSON Schema.

        Args:
            json_data: The dict to validate.

        Returns:
            True if valid, raises ValueError if invalid.
        """
        from jsonschema import validate, ValidationError

        try:
            validate(instance=json_data, schema=PRD_EXTRACTION_SCHEMA)
            return True
        except ValidationError as e:
            raise ValueError(f"JSON Schema validation failed: {e.message}") from e