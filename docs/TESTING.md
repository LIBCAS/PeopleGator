# Testing

Tests focus on PeopleGator's document-processing pipeline: loading pages, running processing engines, matching identities, and saving annotations.

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

The repository's automated test suite is being established. Once `pytest` is configured, run:

```bash
python -m pytest -q
```

To check Python syntax in the processing code:

```bash
python -m compileall -q people_gator user_scripts
```

## How to write new tests

1. Add a `tests/test_*.py` file for the relevant processing component.
2. Use small synthetic images, ALTO/PAGE XML and metadata fixtures in `tests/resources/`.
3. Mock face-detection models, LLM calls and database lookups; use temporary output directories.
4. Check the resulting face regions, identities and XML structure, including preservation of existing document content.
5. Cover typical, empty and error cases. Run the tests and report the results in the PR.

See [Output formats](OUTPUT_FORMATS.md) for ALTO and PAGE XML examples.
