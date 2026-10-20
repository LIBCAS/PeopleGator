# Testing

Tests focus on PeopleGator's document-processing pipeline: loading pages, running processing engines, matching identities, and saving annotations. For a feature or bug fix, derive test cases from the issue's acceptance criteria and reproduce the reported bug before fixing it when practical.

## What should be tested

| Area | Important cases |
| --- | --- |
| Document loading | Page images, ALTO/PAGE layouts, metadata, and engine configuration/order |
| Face detection | Source-region filtering, bounding boxes, five landmarks, zero or multiple faces |
| LLM face assignment | Names proposed from image/OCR/caption context, single and batch results, missing responses |
| Entity matching | One, multiple or no person candidates; ambiguous and unassigned faces |
| ALTO XML | Face blocks, person and face tags, MODS references, coordinates, and existing OCR content |
| PAGE XML | Face regions, polygon coordinates, identity metadata, and source-region references |

Use synthetic documents and mocked model outputs or person-database responses so tests remain fast and repeatable. Include XML round-trip tests as the import functionality is implemented.

## How to run tests

The automated test suite and reproducible dependencies are being established. Once `pytest` is configured, run the focused test module first, then the full suite:

```bash
python -m pytest -q tests/test_relevant_component.py
python -m pytest -q
```

Replace the example module path with the tests added or modified. Confirm that the runner **collected and executed tests** and check its exit status.

For a syntax check of the processing code, run:

```bash
python -m compileall -q people_gator user_scripts
```

Syntax checks complement behavioral tests; they do not prove an issue is implemented. When dependencies or test tooling are unavailable, record the exact blocker and which acceptance criteria remain unverified. Keep the PR in draft while essential validation is incomplete.

## How to write new tests

1. Translate the issue's acceptance criteria into specific test cases. For a bug, add a regression case that exposes the old behavior when feasible.
2. Add `tests/test_*.py` files for the relevant processing components. Use small synthetic images, ALTO/PAGE XML and metadata fixtures in `tests/resources/`.
3. Mock face-detection models, LLM calls and person-database responses; use temporary output directories.
4. Check resulting face regions, identities and XML structure, including existing document content. Cover typical, empty and error cases.
5. Run focused and available full-suite checks. In the PR, map each acceptance criterion to the test or other evidence that verifies it, and report test outcomes and any remaining gaps.

See [Output formats](OUTPUT_FORMATS.md) for ALTO and PAGE XML examples.
