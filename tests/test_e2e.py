"""End-to-end regression tests for the autoPRD pipeline.

Run with:  .venv/bin/python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from prd_parser.api import app
from prd_parser.ast_parser import extract_structural_context
from prd_parser.extractor import Extractor
from prd_parser.parsers import MarkdownPRDParser

SAMPLE_PRD = """# Login PRD

REQ-042 User login

## Functional Specification
Users must be able to log in with their email and password.

## Acceptance Criteria
1. Given valid credentials, when the user logs in, then a session is created.
2. When the password is wrong, then an error is shown.

## Edge Case Assumptions
- Users may be offline while attempting to log in.
- Sessions expire after 24 hours.
"""

def _make_pdf(lines: list[str]) -> bytes:
    """Build a tiny, valid single-page PDF for parser tests."""
    text = "BT /F1 12 Tf 72 720 Td " + " ".join(
        f"({line}) Tj 0 -20 Td" for line in lines
    ) + " ET"
    stream = text.encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        (
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    chunks = [b"%PDF-1.4\n"]
    offsets = []
    position = len(chunks[0])
    for index, body in enumerate(objects, start=1):
        entry = f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
        offsets.append(position)
        chunks.append(entry)
        position += len(entry)

    xref_position = position
    xref = [f"xref\n0 {len(objects) + 1}\n", "0000000000 65535 f \n"]
    xref.extend(f"{offset:010d} 00000 n \n" for offset in offsets)
    xref.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF\n"
    )
    chunks.append("".join(xref).encode())
    return b"".join(chunks)


SAMPLE_CODE = '''"""Authentication helpers."""


def login(email: str, password: str) -> bool:
    """Log a user in when the credentials are present."""
    if not email or not password:
        return False
    return True
'''


class APITestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_cors_header(self) -> None:
        response = self.client.get("/health", headers={"Origin": "http://localhost:8765"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("access-control-allow-origin"), "*")

    def test_ui_is_served(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("autoPRD", response.text)

    def test_parse_prd_text(self) -> None:
        response = self.client.post(
            "/parse-prd",
            json={
                "prd_text": SAMPLE_PRD,
                "source_format": "markdown",
                "use_llm": False,
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["requirement_id"], "REQ-042")
        self.assertIn("log in with their email", payload["functional_specification"])
        self.assertEqual(len(payload["acceptance_criteria"]), 2)
        self.assertIn("session is created", payload["acceptance_criteria"][0])
        self.assertEqual(len(payload["edge_case_assumptions"]), 2)
        self.assertEqual(payload["extraction_method"], "heuristic")

    def test_parse_prd_rejects_invalid_format(self) -> None:
        response = self.client.post(
            "/parse-prd",
            json={"prd_text": SAMPLE_PRD, "source_format": "docx", "use_llm": False},
        )
        self.assertEqual(response.status_code, 400)

    def test_upload_single_markdown_file(self) -> None:
        response = self.client.post(
            "/upload-file",
            files={"file": ("login.md", SAMPLE_PRD, "text/markdown")},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["processed"], 1)
        self.assertEqual(payload["failed"], 0)
        result = payload["results"][0]
        self.assertEqual(result["filename"], "login.md")
        self.assertEqual(result["requirement_id"], "REQ-042")
        self.assertEqual(result["source_format"], "markdown")
        self.assertGreater(result["word_count"], 10)

    def test_upload_multiple_files_and_report_invalid(self) -> None:
        response = self.client.post(
            "/upload-file",
            files=[
                ("file", ("one.md", SAMPLE_PRD, "text/markdown")),
                ("file", ("two.markdown", "# Two\nREQ-007 Thing\n", "text/markdown")),
                ("file", ("image.png", b"not-an-image", "image/png")),
            ],
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["processed"], 2)
        self.assertEqual(payload["failed"], 1)
        self.assertEqual(
            {result["requirement_id"] for result in payload["results"]},
            {"REQ-042", "REQ-007"},
        )
        self.assertEqual(payload["errors"][0]["filename"], "image.png")

    def test_upload_only_invalid_file_returns_400(self) -> None:
        response = self.client.post(
            "/upload-file",
            files={"file": ("notes.txt", "hello", "text/plain")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["processed"], 0)

    def test_upload_pdf_file(self) -> None:
        pdf = _make_pdf(
            [
                "REQ-042 Login",
                "1. Given a user logs in, then a session is created.",
            ]
        )
        response = self.client.post(
            "/upload-file",
            files={"file": ("login.pdf", pdf, "application/pdf")},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["results"][0]
        self.assertEqual(result["source_format"], "pdf")
        self.assertEqual(result["requirement_id"], "REQ-042")
        self.assertEqual(len(result["acceptance_criteria"]), 1)

    def test_upload_corrupt_pdf_reports_error(self) -> None:
        response = self.client.post(
            "/upload-file",
            files={"file": ("broken.pdf", b"not a pdf", "application/pdf")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["processed"], 0)
        self.assertEqual(response.json()["errors"][0]["filename"], "broken.pdf")

    def test_generate_functional_tests_python(self) -> None:
        response = self.client.post(
            "/generate-functional-tests",
            json={
                "prd_requirement_id": "REQ-042",
                "prd_functional_spec": "User login",
                "prd_acceptance_criteria": ["Given valid credentials, the user logs in"],
                "prd_edge_case_assumptions": [],
                "code_source": SAMPLE_CODE,
                "language": "python",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["format"], "pytest")
        self.assertEqual(payload["language"], "python")
        self.assertEqual(payload["code_context"]["functions"], ["login"])
        self.assertIn("if", payload["code_context"]["logic_blocks"])
        self.assertIn("login(email, password) -> bool", payload["prompt"])
        self.assertIn("test", payload["prompt"].lower())

    def test_generate_functional_tests_javascript(self) -> None:
        response = self.client.post(
            "/generate-functional-tests",
            json={
                "prd_requirement_id": "REQ-042",
                "prd_functional_spec": "User login",
                "prd_acceptance_criteria": ["Given valid credentials, the user logs in"],
                "code_source": "export function login(email, password) { return true; }",
                "language": "javascript",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["format"], "jest")
        self.assertEqual(payload["language"], "javascript")
        self.assertIn("export function login", payload["prompt"])

    def test_generate_rejects_invalid_language(self) -> None:
        response = self.client.post(
            "/generate-functional-tests",
            json={
                "prd_requirement_id": "REQ-001",
                "prd_functional_spec": "Thing",
                "code_source": "def thing(): pass",
                "language": "ruby",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_validate_code(self) -> None:
        response = self.client.post(
            "/validate-code",
            json={
                "prd_requirement_id": "REQ-042",
                "prd_functional_spec": "User login",
                "prd_acceptance_criteria": [
                    "Given valid credentials, when the user logs in, then a session is created"
                ],
                "prd_edge_case_assumptions": [],
                "generated_tests": {
                    "tests": [{"name": "test_login_valid", "function": "login"}]
                },
                "code_structural_context": {
                    "filename": "auth.py",
                    "functions": [{"name": "login", "docstring": "Log a user in."}],
                    "classes": [],
                    "logic_blocks": [{"block_type": "if"}],
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["overall_coverage"], 100.0)
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["missing_assertions"], [])


class _FakeCompletions:
    def __init__(self) -> None:
        self.prompt = ""

    def create(self, **kwargs):
        self.prompt = kwargs["messages"][0]["content"]

        class Message:
            content = (
                "```json\n"
                '{"requirement_id": "REQ-042",'
                ' "functional_specification": {"specification": "User login",'
                ' "category": null, "complexity": null},'
                ' "acceptance_criteria": [{"criterion": "Given valid credentials,'
                ' then a session is created"}],'
                ' "edge_case_assumptions": [], "source_format": "markdown"}'
                "\n```"
            )

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]

        return Response()


class _FakeClient:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()

        class Chat:
            completions = self.completions

        self.chat = Chat()


class ExtractorTestCase(unittest.TestCase):
    def test_llm_extraction_parses_fenced_json(self) -> None:
        client = _FakeClient()
        extraction = Extractor(llm_client=client).extract(SAMPLE_PRD, "markdown")

        self.assertEqual(extraction.requirement_id, "REQ-042")
        self.assertEqual(extraction.functional_specification.specification, "User login")
        self.assertEqual(len(extraction.acceptance_criteria), 1)
        # The prompt must contain the real schema, not the unresolved placeholder.
        self.assertIn('"requirement_id"', client.completions.prompt)
        self.assertNotIn("<JSON_SCHEMA_PLACEHOLDER>", client.completions.prompt)

    def test_llm_extraction_validates_schema(self) -> None:
        extraction = Extractor(llm_client=_FakeClient()).extract(SAMPLE_PRD, "markdown")
        self.assertTrue(extraction.validate_json_schema())


class ParserTestCase(unittest.TestCase):
    def test_markdown_parser_preserves_lines(self) -> None:
        parsed = MarkdownPRDParser().parse_bytes(SAMPLE_PRD.encode("utf-8"), "login.md")
        self.assertIn("\n", parsed.text)
        self.assertIn("## Acceptance Criteria", parsed.text)
        self.assertIn("REQ-042", parsed.text)

    def test_ast_parser_handles_nested_and_top_level_loops(self) -> None:
        source = """
import asyncio

async def fetch(items):
    for item in items:
        if item:
            print(item)
    while items:
        break

for value in range(3):
    print(value)
"""
        result = extract_structural_context(source, "loops.py")
        self.assertTrue(result.success, result.error_message)
        self.assertEqual([function.name for function in result.structural_context.functions], ["fetch"])
        self.assertTrue(result.structural_context.functions[0].is_async)
        block_types = {block.block_type for block in result.structural_context.logic_blocks}
        self.assertTrue({"for", "if", "while"}.issubset(block_types))

    def test_ast_parser_extracts_generic_return_annotation(self) -> None:
        result = extract_structural_context(
            "from typing import List\n\ndef total(items) -> List[float]:\n    return items\n",
            "total.py",
        )
        self.assertTrue(result.success)
        self.assertEqual(result.structural_context.functions[0].returns, "List[float]")


if __name__ == "__main__":
    unittest.main()
