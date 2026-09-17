"""Data models and JSON Schema for PRD parsing output."""

from __future__ import annotations

from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any


class AcceptanceCriterion(BaseModel):
    """A single acceptance criterion statement."""

    criterion: str = Field(
        ...,
        description="The acceptance criterion text.",
    )
    category: Optional[str] = Field(
        None,
        description="Optional category (e.g., 'functional', 'ui', 'performance').",
    )
    priority: Optional[str] = Field(
        None,
        description="Optional priority level (e.g., 'P0', 'P1', 'P2').",
    )

    @validator("criterion")
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Acceptance criterion text cannot be empty.")
        return v.strip()


class EdgeCaseAssumption(BaseModel):
    """An edge-case assumption extracted from the PRD."""

    assumption: str = Field(
        ...,
        description="The edge-case assumption text.",
    )
    context: Optional[str] = Field(
        None,
        description="Optional context or triggering condition.",
    )
    impact: Optional[str] = Field(
        None,
        description="Optional description of impact if assumption fails.",
    )

    @validator("assumption")
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Edge-case assumption text cannot be empty.")
        return v.strip()


class FunctionalSpecification(BaseModel):
    """A functional specification extracted from the PRD."""

    specification: str = Field(
        ...,
        description="The functional specification text.",
    )
    category: Optional[str] = Field(
        None,
        description="Optional category (e.g., 'user-flow', 'data', 'integration').",
    )
    complexity: Optional[str] = Field(
        None,
        description="Optional complexity indicator (e.g., 'low', 'medium', 'high').",
    )

    @validator("specification")
    def non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Functional specification text cannot be empty.")
        return v.strip()


class PRDExtraction(BaseModel):
    """Structured extraction result from a PRD."""

    requirement_id: str = Field(
        ...,
        description="Unique requirement identifier (e.g., REQ-001).",
    )
    functional_specification: FunctionalSpecification = Field(
        ...,
        description="The main functional specification.",
    )
    acceptance_criteria: List[AcceptanceCriterion] = Field(
        default_factory=list,
        description="List of acceptance criteria.",
    )
    edge_case_assumptions: List[EdgeCaseAssumption] = Field(
        default_factory=list,
        description="List of edge-case assumptions.",
    )
    source_format: str = Field(
        ...,
        description="Input format: 'pdf' or 'markdown'.",
    )
    raw_text_snippet: Optional[str] = Field(
        None,
        description="Optional snippet of raw text that was used for extraction.",
    )

    @validator("requirement_id")
    def valid_id_format(cls, v: str) -> str:
        """Requirement ID must match REQ-NNN pattern or similar."""
        import re
        if not re.match(r"^REQ-\d{3,}$", v, re.IGNORECASE):
            raise ValueError(
                f"Requirement ID '{v}' does not match expected pattern REQ-NNN."
            )
        return v

    @validator("source_format")
    def valid_format(cls, v: str) -> str:
        if v not in ("pdf", "markdown"):
            raise ValueError(f"Source format must be 'pdf' or 'markdown', got '{v}'.")
        return v

    def to_json(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "requirement_id": self.requirement_id,
            "functional_specification": {
                "specification": self.functional_specification.specification,
                "category": self.functional_specification.category,
                "complexity": self.functional_specification.complexity,
            },
            "acceptance_criteria": [
                {
                    "criterion": ac.criterion,
                    "category": ac.category,
                    "priority": ac.priority,
                }
                for ac in self.acceptance_criteria
            ],
            "edge_case_assumptions": [
                {
                    "assumption": eca.assumption,
                    "context": eca.context,
                    "impact": eca.impact,
                }
                for eca in self.edge_case_assumptions
            ],
            "source_format": self.source_format,
            "raw_text_snippet": self.raw_text_snippet,
        }

    def model_validate_json(cls, json_str: str) -> PRDExtraction:
        """Validate and parse from JSON string."""
        import json
        data = json.loads(json_str)
        return cls.model_validate(data)


# JSON Schema for output validation (standalone, can be used outside Pydantic)
PRD_EXTRACTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": [
        "requirement_id",
        "functional_specification",
        "acceptance_criteria",
        "edge_case_assumptions",
        "source_format",
    ],
    "properties": {
        "requirement_id": {
            "type": "string",
            "pattern": r"^REQ-\d{3,}$",
            "description": "Unique requirement identifier (e.g., REQ-001).",
        },
        "functional_specification": {
            "type": "object",
            "required": ["specification"],
            "properties": {
                "specification": {
                    "type": "string",
                    "description": "The functional specification text.",
                },
                "category": {
                    "type": ["string", "null"],
                    "description": "Optional category.",
                },
                "complexity": {
                    "type": ["string", "null"],
                    "description": "Optional complexity indicator.",
                },
            },
            "additionalProperties": False,
        },
        "acceptance_criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["criterion"],
                "properties": {
                    "criterion": {
                        "type": "string",
                        "description": "The acceptance criterion text.",
                    },
                    "category": {
                        "type": ["string", "null"],
                        "description": "Optional category.",
                    },
                    "priority": {
                        "type": ["string", "null"],
                        "description": "Optional priority level.",
                    },
                },
                "additionalProperties": False,
            },
            "description": "List of acceptance criteria.",
        },
        "edge_case_assumptions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["assumption"],
                "properties": {
                    "assumption": {
                        "type": "string",
                        "description": "The edge-case assumption text.",
                    },
                    "context": {
                        "type": ["string", "null"],
                        "description": "Optional context or triggering condition.",
                    },
                    "impact": {
                        "type": ["string", "null"],
                        "description": "Optional description of impact if assumption fails.",
                    },
                },
                "additionalProperties": False,
            },
            "description": "List of edge-case assumptions.",
        },
        "source_format": {
            "type": "string",
            "enum": ["pdf", "markdown"],
            "description": "Input format: 'pdf' or 'markdown'.",
        },
        "raw_text_snippet": {
            "type": ["string", "null"],
            "description": "Optional snippet of raw text that was used for extraction.",
        },
    },
    "additionalProperties": False,
}