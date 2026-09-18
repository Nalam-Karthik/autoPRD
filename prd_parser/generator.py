"""Functional test case generator for PRD-extracted requirements.

Takes structured PRDExtraction JSON output and generates:
  1. BDD (Gherkin Given-When-Then) test cases
  2. Tabular test case format

Each generated test includes:
  - Explicit test title
  - Concrete steps (Given/When/Then)
  - Input parameters derived from the requirement
  - Expected results based on acceptance criteria
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from prd_parser.models import PRDExtraction, FunctionalSpecification, AcceptanceCriterion, EdgeCaseAssumption


def _generate_test_title(req_id: str, spec: FunctionalSpecification) -> str:
    """Generate a descriptive test title from the requirement ID and specification."""
    base = f"REQ {req_id}"
    if spec.category:
        base += f" [{spec.category}]"
    if spec.complexity:
        base += f" ({spec.complexity})"
    base += f": {spec.specification[:60]}..."
    return base


def _build_bdd_steps(
    req_id: str,
    spec: FunctionalSpecification,
    acceptance_criteria: List[AcceptanceCriterion],
    edge_case_assumptions: List[EdgeCaseAssumption],
) -> List[str]:
    """Build BDD Given-When-Then steps for a requirement.

    Returns a list of strings, each representing one step in Gherkin format.
    """
    steps: List[str] = []

    # Given: Setup context from functional specification
    spec_text = spec.specification or "the system is in a valid state"
    steps.append(f'Given {spec_text.replace(".", "").replace(" the", "").strip()}')

    # When: Action based on acceptance criteria or default action
    if acceptance_criteria:
        first_criterion = acceptance_criteria[0].criterion
        # Extract the "when" part if it follows "Given X, when Y, then Z" pattern
        match = re.search(r"when\s+(.+?)(?:,|$)", first_criterion, re.IGNORECASE)
        if match:
            when_phrase = match.group(1).strip()
            steps.append(f'When {when_phrase}')
        else:
            # Default: trigger the feature
            steps.append(f'When the user initiates the {req_id.lower()} feature')
    else:
        steps.append(f'When the user triggers the {req_id.lower()} functionality')

    # Then: Expected results from acceptance criteria
    if acceptance_criteria:
        for ac in acceptance_criteria:
            criterion = ac.criterion
            # Try to extract "then" part
            then_match = re.search(r"then\s+(.+?)(?:\.|$)", criterion, re.IGNORECASE)
            if then_match:
                then_phrase = then_match.group(1).strip()
                steps.append(f'Then {then_phrase}')
            else:
                # Use the full criterion as the expected result
                steps.append(f'Then {criterion}')
    else:
        # Default expected result: system responds successfully
        steps.append('Then the system responds successfully')

    return steps


def _build_tabular_row(
    req_id: str,
    spec: FunctionalSpecification,
    acceptance_criteria: List[AcceptanceCriterion],
    edge_case_assumptions: List[EdgeCaseAssumption],
) -> Dict[str, str]:
    """Build a tabular test case row dict.

    Columns: Test Title, Given, When, Then, Input Parameters, Expected Results
    """
    # Build input parameters from acceptance criteria parameters
    input_params: List[str] = []
    for ac in acceptance_criteria:
        criterion = ac.criterion
        # Look for parameter patterns like "with X" or "provide Y"
        params = re.findall(r"(?:with|provide|using)\s+(\w+)", criterion, re.IGNORECASE)
        input_params.extend(params)

    # Build Then expected result
    then_results: List[str] = []
    for ac in acceptance_criteria:
        criterion = ac.criterion
        then_match = re.search(r"then\s+(.+?)(?:\.|$)", criterion, re.IGNORECASE)
        if then_match:
            then_results.append(then_match.group(1).strip())
        else:
            then_results.append(criterion)

    # Build Given step
    spec_text = spec.specification or "the system is in a valid state"
    given = spec_text.replace(".", "").strip()

    # Build When step
    when = "trigger the feature"
    if acceptance_criteria:
        first_ac = acceptance_criteria[0].criterion
        match = re.search(r"when\s+(.+?)(?:,|$)", first_ac, re.IGNORECASE)
        if match:
            when = match.group(1).strip()

    # Build Then step
    then = "; ".join(then_results) if then_results else "system responds successfully"

    return {
        "Test Title": _generate_test_title(req_id, spec),
        "Given": given,
        "When": when,
        "Then": then,
        "Input Parameters": ", ".join(input_params) if input_params else "none",
        "Expected Results": "; ".join(then_results) if then_results else "system responds successfully",
    }


def generate_bdd_tests(extraction: PRDExtraction) -> Dict[str, Any]:
    """Generate BDD (Gherkin Given-When-Then) test cases from a PRDExtraction instance.

    Args:
        extraction: A PRDExtraction instance containing extracted requirement data.

    Returns:
        A dict with:
          - "requirement_id": the requirement ID
          - "title": generated test title
          - "bdd_format": Gherkin-formatted test steps (Given/When/Then)
          - "raw_inputs": extracted input parameters
          - "expected_results": expected outcomes from acceptance criteria
    """
    req_id = extraction.requirement_id
    spec = extraction.functional_specification
    acceptance_criteria = extraction.acceptance_criteria
    edge_case_assumptions = extraction.edge_case_assumptions

    bdd_steps = _build_bdd_steps(req_id, spec, acceptance_criteria, edge_case_assumptions)

    # Format as Gherkin feature file style
    bgherkin = f"""Feature: {_generate_test_title(req_id, spec)}

  Scenario: {req_id} functional test
    Given: {bdd_steps[0].replace("Given ", "", 1)}
    When:  {bdd_steps[1].replace("When ", "", 1)}
    Then:  {bdd_steps[2].replace("Then ", "", 1)}
"""

    return {
        "requirement_id": req_id,
        "title": _generate_test_title(req_id, spec),
        "bdd_format": bgherkin,
        "steps": bdd_steps,
        "raw_inputs": _extract_input_parameters(acceptance_criteria),
        "expected_results": _extract_expected_results(acceptance_criteria),
    }


def generate_tabular_tests(extraction: PRDExtraction) -> Dict[str, Any]:
    """Generate tabular test case rows from a PRDExtraction instance.

    Args:
        extraction: A PRDExtraction instance containing extracted requirement data.

    Returns:
        A dict with:
          - "requirement_id": the requirement ID
          - "title": generated test title
          - "tabular_format": dict ready for CSV/JSON serialization with columns:
            Test Title, Given, When, Then, Input Parameters, Expected Results
    """
    tabular_row = _build_tabular_row(
        extraction.requirement_id,
        extraction.functional_specification,
        extraction.acceptance_criteria,
        extraction.edge_case_assumptions,
    )

    return {
        "requirement_id": extraction.requirement_id,
        "title": tabular_row["Test Title"],
        "tabular_format": tabular_row,
    }


def _extract_input_parameters(acceptance_criteria: List[AcceptanceCriterion]) -> List[str]:
    """Extract unique input parameter names from acceptance criteria."""
    params: set[str] = set()
    for ac in acceptance_criteria:
        criterion = ac.criterion
        found = re.findall(r"(?:with|provide|using)\s+(\w+)", criterion, re.IGNORECASE)
        params.update(found)
    return sorted(params)


def _extract_expected_results(acceptance_criteria: List[AcceptanceCriterion]) -> List[str]:
    """Extract expected result statements from acceptance criteria."""
    results: list[str] = []
    for ac in acceptance_criteria:
        criterion = ac.criterion
        then_match = re.search(r"then\s+(.+?)(?:\.|$)", criterion, re.IGNORECASE)
        if then_match:
            results.append(then_match.group(1).strip())
        else:
            results.append(criterion)
    return results


def generate_all_formats(extraction: PRDExtraction) -> Dict[str, Any]:
    """Generate test cases in both BDD and tabular formats for a single extraction.

    Args:
        extraction: A PRDExtraction instance.

    Returns:
        A dict containing both BDD and tabular test case outputs.
    """
    return {
        "requirement_id": extraction.requirement_id,
        "bdd": generate_bdd_tests(extraction),
        "tabular": generate_tabular_tests(extraction),
    }


# Example usage / CLI entry point
if __name__ == "__main__":
    # Sample PRDExtraction for demonstration
    sample = PRDExtraction(
        requirement_id="REQ-001",
        functional_specification=FunctionalSpecification(
            specification="User can log in to the system using valid credentials",
            category="authentication",
            complexity="medium",
        ),
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion="Given user is on the login page, when user enters valid credentials and submits, then login succeeds"
            ),
            AcceptanceCriterion(
                criterion="Given user is on the login page, when user enters invalid credentials, then error message is displayed"
            ),
        ],
        edge_case_assumptions=[
            EdgeCaseAssumption(
                assumption="User has an active account",
                context="login attempt",
                impact="login may fail",
            ),
        ],
        source_format="pdf",
    )

    result = generate_all_formats(sample)
    print("=== BDD Format ===")
    print(result["bdd"]["bdd_format"])
    print("\n=== Tabular Format ===")
    print(json.dumps(result["tabular"]["tabular_format"], indent=2))