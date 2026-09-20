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


class ImportInfo(BaseModel):
    """Information about a Python import statement."""

    module: str = Field(
        ...,
        description="The imported module name.",
    )
    alias: Optional[str] = Field(
        None,
        description="The import alias, if any.",
    )
    line: int = Field(
        ...,
        description="Line number where the import appears.",
    )
    is_stdlib: bool = Field(
        False,
        description="Whether this is a standard library module.",
    )
    is_third_party: bool = Field(
        False,
        description="Whether this is a third-party package.",
    )
    is_local: bool = Field(
        False,
        description="Whether this is a local module import.",
    )



class FunctionInfoAST(BaseModel):
    """Information about a Python function extracted via AST."""

    name: str = Field(
        ...,
        description="The function name.",
    )
    line: int = Field(
        ...,
        description="Line number where the function starts.",
    )
    col: int = Field(
        ...,
        description="Column offset where the function starts.",
    )
    end_line: int = Field(
        ...,
        description="Line number where the function ends.",
    )
    end_col: int = Field(
        ...,
        description="Column offset where the function ends.",
    )
    args: List[str] = Field(
        default_factory=list,
        description="List of argument names (excluding 'self'/'cls').",
    )
    returns: Optional[str] = Field(
        None,
        description="Return type annotation, if any.",
    )
    is_async: bool = Field(
        False,
        description="Whether the function is async.",
    )
    is_method: bool = Field(
        False,
        description="Whether this is a method (inside a class).",
    )
    class_name: Optional[str] = Field(
        None,
        description="Name of the containing class, if any.",
    )


class MethodInfoAST(FunctionInfoAST):
    """Information about a Python method extracted via AST."""

    pass


class ClassInfoAST(BaseModel):
    """Information about a Python class extracted via AST."""

    name: str = Field(
        ...,
        description="The class name.",
    )
    line: int = Field(
        ...,
        description="Line number where the class starts.",
    )
    col: int = Field(
        ...,
        description="Column offset where the class starts.",
    )
    end_line: int = Field(
        ...,
        description="Line number where the class ends.",
    )
    end_col: int = Field(
        ...,
        description="Column offset where the class ends.",
    )
    bases: List[str] = Field(
        default_factory=list,
        description="List of base class names.",
    )
    decorator_names: List[str] = Field(
        default_factory=list,
        description="List of decorator names applied to the class.",
    )
    methods: List[MethodInfoAST] = Field(
        default_factory=list,
        description="List of methods defined within this class.",
    )


class structural_context_contextAST(BaseModel):
    """Root container for all extracted structural context from AST parsing."""

    filename: str = Field(
        ...,
        description="Name of the file that was parsed.",
    )
    imports: List[ImportInfo] = Field(
        default_factory=list,
        description="List of import statements found.",
    )
    classes: List[ClassInfoAST] = Field(
        default_factory=list,
        description="List of class definitions found.",
    )
    functions: List[FunctionInfoAST] = Field(
        default_factory=list,
        description="List of top-level function definitions found.",
    )
    raw_source: Optional[str] = Field(
        None,
        description="Optional raw source text that was parsed.",
    )


class ASTExtractionResult(BaseModel):
    """Result of AST-based source code extraction."""

    structural_context: structural_context_contextAST = Field(
        ...,
        description="The extracted structural context.",
    )
    success: bool = Field(
        True,
        description="Whether the extraction succeeded.",
    )
    error_message: Optional[str] = Field(
        None,
        description="Error message if extraction failed.",
    )

    class Config:
        """Pydantic configuration."""

        use_enum_values = True


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