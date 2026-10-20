# autoPRD — PRD-to-Code Test Generation Pipeline

## Overview

`autoPRD` is a local studio and API for turning Product Requirement Documents (PRDs) into code-level functional tests. The system:

1. **Parses PRDs** (PDF or Markdown) to extract structured requirements
2. **Analyzes Python code** using AST parsing to extract structural context
3. **Generates test prompts** combining PRD requirements with code context
4. **Validates generated tests** against acceptance criteria and reports coverage gaps

The included web UI supports drag-and-drop upload or choosing files from your computer.

## Architecture

```mermaid
flowchart TD
    subgraph "Input Layer"
        PRD[PRD Document (PDF/Markdown)]
        Code[Python Source Code]
    end
    
    subgraph "Processing Layer"
        PRD_Parser[PRD Parser] -->|Extracts Requirements| PRD_Structured[Structured PRD Data]
        Code_Parser[AST Parser] -->|Extracts Context| Code_Structured[Code Structural Context]
        PRD_Structured + Code_Structured -->|Combined Prompt| Test_Prompt_Engine[Test Prompt Engine]
    end
    
    subgraph "Output Layer"
        LLM[LLM Client] -->|Generates Test Code| Generated_Tests[PyTest/Jest Tests]
        Verifier[LLM Judge] -->|Validates Compliance| Verification_Report[Coverage Score & Recommendations]
    end
    
    style PRD_Parser fill:#e1f5fe,stroke:#01579a
    style Code_Parser fill:#e1f5fe,stroke:#01579a
    style Test_Prompt_Engine fill:#fff3e0,stroke:#fb8c00
    style Verifier fill:#e8f5e9,stroke:#2e7d32
```

## Installation

```bash
# From the repository root
python -m venv .venv
source .venv/bin/activate

# Install dependencies and the package
pip install -r requirements.txt
pip install -e .
```

### Requirements

- Python 3.10+
- FastAPI & Uvicorn
- Pydantic v2
- pdfplumber (for PDF parsing)
- jsonschema
- openai (optional, only for LLM extraction)

### Requirements File

```text
fastapi>=0.110,<1.0
uvicorn>=0.27
pydantic>=2.5
python-multipart>=0.0.9
pdfplumber>=0.10
jsonschema>=4.20
openai>=1.30
```

### Running the app

```bash
uvicorn prd_parser.api:app --reload
```

Then open <http://localhost:8000/> to use the autoPRD upload UI. The API docs are at
<http://localhost:8000/docs>.

The UI can also be served from any static file server; CORS is enabled for local
origins by default (`AUTOPRD_CORS_ORIGINS` can override the allowed origins).

### LLM configuration (optional)

`parse_prd_from_file()`, `parse_prd_from_text()`, and `POST /parse-prd` can use an
OpenAI-compatible LLM for extraction. Configure one of:

```bash
export OPENAI_API_KEY=...        # or GEMINI_API_KEY for Gemini's compatible endpoint
export OPENAI_BASE_URL=...       # optional custom endpoint
export PRD_LLM_MODEL=...         # optional model override
```

Without credentials the API automatically falls back to the built-in deterministic
parser, so uploads and the web UI always work offline.

## Quick Start

```python
from prd_parser import (
    parse_prd_from_file,
    parse_python_from_source,
    CodeTestPromptEngine,
    verify,
)

# 1. Parse PRD from file
prd = parse_prd_from_file("product_requirements.pdf")

# 2. Parse Python code context
code_result = parse_python_from_source("""
def calculate_total(items: list) -> float:
    \"\"\"Calculate the total of a list of numbers.\"\"\"
    return sum(items)
""", "calculator.py")

# 3. Generate test prompts
engine = CodeTestPromptEngine()
prompt_result = engine.generate_pytest_tests(prd, code_result.structural_context)

# 4. Send prompt to LLM to get actual test code
# The prompt contains instructions for the LLM to generate PyTest tests

# 5. Validate generated tests against the PRD
verdict = verify(prd, generated_tests_dict, code_result.structural_context)

print(f"Coverage: {verdict['overall_coverage']:.1f}%")
print(f"Passed: {verdict['passed']}")
print(f"Missing: {len(verdict['missing_assertions'])} assertions")
print(f"Recommendations: {verdict['recommendations']}")
```

`parse_prd_from_file()` and `parse_prd_from_text()` require LLM credentials. The HTTP
upload/parse endpoints fall back to the deterministic parser automatically.

## API Reference

### Endpoints

#### `GET /`
- **Description**: Serves the autoPRD upload UI (`index.html`).

#### `GET /health`
- **Description**: Health check endpoint
- **Response**: `{"status": "ok", "message": "PRD-to-Code API is running"}`

#### `POST /parse-prd`
- **Description**: Parse a PRD document and extract structured requirements
- **Request Body**:
  - `prd_text`: The PRD text content (required)
  - `source_format`: "pdf" or "markdown" (default: "markdown")
  - `use_llm`: Try LLM extraction first, with deterministic fallback (default: true)
- **Response**: `requirement_id`, `functional_specification`, `acceptance_criteria`, `edge_case_assumptions`, `source_format`, `extraction_method`

#### `POST /upload-file`
- **Description**: Upload one or more PDF/Markdown PRD files and parse each one.
- **Request**: `multipart/form-data` with one or more `file` fields (`.pdf`, `.md`, `.markdown`).
- **Response**:

```json
{
  "processed": 1,
  "failed": 0,
  "results": [
    {
      "filename": "login.md",
      "requirement_id": "REQ-042",
      "functional_specification": "Users must be able to log in.",
      "acceptance_criteria": ["Given valid credentials, then a session is created."],
      "edge_case_assumptions": [{"assumption": "Users may be offline.", "context": "", "impact": ""}],
      "source_format": "markdown",
      "word_count": 42
    }
  ],
  "errors": []
}
```

Returns HTTP 400 when no file could be parsed. Partially invalid batches return 200
with the failed filenames in `errors`.

#### `POST /generate-functional-tests`
- **Description**: Generate functional test prompts from PRD and code context
- **Request Body**:
  - `prd_requirement_id`: PRD requirement identifier
  - `prd_functional_spec`: Functional specification text
  - `prd_acceptance_criteria`: List of acceptance criterion strings
  - `prd_edge_case_assumptions`: List of edge case assumption dicts
  - `code_source`: Python source code to analyze for structural context
  - `language`: "python", "javascript", or "typescript" (default: "python")
- **Response**: Dict with `prompt`, `format`, `language`, and `code_context`

#### `POST /validate-code`
- **Description**: Validate generated code tests against PRD acceptance criteria
- **Request Body**:
  - `prd_requirement_id`: PRD requirement identifier
  - `prd_functional_spec`: Functional specification text
  - `prd_acceptance_criteria`: List of acceptance criterion strings
  - `prd_edge_case_assumptions`: List of edge case assumption dicts
  - `generated_tests`: Generated test cases dict (from prompt engine output)
  - `code_structural_context`: Structural context from code parsing
- **Response**: `ValidateCodeResponse` with `overall_coverage`, `passed`, `missing_assertions`, `discrepancies`, `test_summary`, `recommendations`

### Example Workflow

```bash
# 1. Parse PRD
curl -X POST "http://localhost:8000/parse-prd" \
  -H "Content-Type: application/json" \
  -d '{"source_format": "markdown", "prd_text": "# Your PRD content..."}'

# 2. Generate tests
curl -X POST "http://localhost:8000/generate-functional-tests" \
  -H "Content-Type: application/json" \
  -d '{
    "prd_requirement_id": "REQ-001",
    "prd_functional_spec": "User authentication functionality",
    "prd_acceptance_criteria": ["Given user logs in with valid credentials, when session is created, then user is authenticated"],
    "code_source": "def login(username, password): ...",
    "language": "python"
  }'

# 3. Validate tests
curl -X POST "http://localhost:8000/validate-code" \
  -H "Content-Type: application/json" \
  -d '{
    "prd_requirement_id": "REQ-001",
    "prd_functional_spec": "User authentication functionality",
    "prd_acceptance_criteria": ["Given user logs in with valid credentials, when session is created, then user is authenticated"],
    "generated_tests": {"tests": [{"name": "test_login_valid", "function": "login", ...}]},
    "code_structural_context": {"functions": [{"name": "login", ...}], "classes": [], "logic_blocks": []}
  }'
```

## Pipeline Details

### PRD Parser

The PRD parser extracts the following from PRD text:

- **Requirement ID**: Pattern `REQ-NNN` (e.g., `REQ-001`)
- **Functional Specification**: First sentence of the PRD
- **Acceptance Criteria**: Numbered lines starting with `Given`, `When`, or `Then` (e.g., `1. Given user...`)
- **Edge Case Assumptions**: Lines following the `### Edge Case Assumptions` heading

### Code Parser (AST)

The AST parser extracts from Python source code:

- **Functions**: Top-level function definitions with names, arguments, return types, and docstrings
- **Classes**: Class definitions with methods, base classes, and docstrings
- **Logic Blocks**: if/for/while/try/except/with blocks with conditions and loop variables
- **Imports**: Module imports with stdlib/third-party/local classification

### Test Prompt Engine

The prompt engine builds a comparison prompt that asks the LLM to:

1. Analyze PRD requirements against code context
2. Identify gaps and discrepancies
3. Generate comprehensive unit/integration test cases
4. Return results in strict JSON format

The prompt includes:
- PRD requirements (requirement ID, functional spec, acceptance criteria, edge cases)
- Code context (imports, classes, functions, logic blocks)
- Detailed comparison task instructions
- JSON schema for strict output validation

### Verifier

The deterministic verifier evaluates generated tests against PRD requirements and
outputs:

- **overall_coverage**: Percentage of PRD acceptance criteria covered (0-100)
- **passed**: Whether coverage meets the threshold (default: 80%)
- **missing_assertions**: List of PRD criteria not covered by any test
- **discrepancies**: Code vs PRD mismatches (function purpose mismatches, missing edge case handling)
- **test_summary**: Test count, covered criteria, total criteria, coverage percentage
- **recommendations**: Actionable improvement suggestions

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The system uses file-based caching (`.cache/` directory) by default, with keys generated from request parameters. To use Redis, replace the cache functions in `prd_parser/api.py` with Redis operations.

## Project Structure

```
.
├── index.html              # autoPRD web UI (drag & drop + file picker)
├── pyproject.toml
├── requirements.txt
├── tests/
│   └── test_e2e.py         # End-to-end API/parser regression tests
└── prd_parser/
    ├── __init__.py         # Public library API
    ├── api.py              # FastAPI application
    ├── ast_parser.py       # AST-based code parser
    ├── code_test_generator.py  # Prompt engine for test generation
    ├── extractor.py        # LLM-based PRD extraction
    ├── generator.py        # Test case generator
    ├── main.py             # Library/CLI entry points
    ├── models.py           # Data models and schemas
    ├── parsers.py          # PDF/Markdown PRD parsers
    └── verifier.py         # Coverage verification
```

## Edge Cases & Optimizations

### Known Edge Cases

1. **Empty PRD text**: Returns default requirement ID `REQ-001` and empty specifications
2. **No acceptance criteria**: Coverage shows 0%, verifier recommends adding tests
3. **Code with only classes**: Functions inside classes are captured as methods, not top-level functions
4. **Markdown PRDs without numbered criteria**: Acceptance criteria extraction may return empty list

### Token Count Optimization

Prompt templates are optimized to reduce token count by:

- Using concise instruction language
- Embedding JSON schema directly in the prompt
- Minimizing redundant explanations
- Using structured format specifiers instead of natural language descriptions

Typical prompt length: 2,500-3,500 characters (vs. 5,000+ for unoptimized prompts)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Run the existing test suite
5. Submit a pull request

## License

This project is licensed under the MIT License.
