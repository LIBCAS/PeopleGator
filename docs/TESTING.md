# Testing

PeopleGator tests should cover document processing, face detection and assignment, identity matching, XML output, and API/worker integration using reproducible fixtures.

## What should be tested

| Area | Important cases |
| --- | --- |
| Document and CLI | Input images, ALTO/PAGE layouts, document metadata, engine order, invalid configuration |
| Face detection | Region filtering, empty/multiple detections, bounding boxes, five landmarks, confidence |
| LLM name assignment | Single and batch requests, OCR/caption context, empty responses, parallel modes |
| Entity matching | One/multiple/no candidate entities, LLM disambiguation, person creation, API errors |
| ALTO XML | `ComposedBlock`, face `LayoutTag` and person `NamedEntityTag`, `TAGREFS`, MODS links and landmarks |
| PAGE XML | Face `ImageRegion`, polygon, JSON `custom` metadata and source-region reference |
| PeopleGatorApp API | Import/export payloads, entity IDs, partial failures and repeat processing |
| DocAPI | Client submission, worker arguments, result delivery, processing errors |

XML tests should also verify preservation of existing OCR and AnnoPage annotations. Add read–write–read regression cases when the ALTO and PAGE face-import work in [TODO.md](TODO.md) is implemented.

## How to run tests

A Python test suite and reproducible development dependencies are planned. The intended standard test command after `pytest` is configured is:

```bash
python -m pytest -q
```

The Python sources can currently be checked for syntax from the repository root:

```bash
python -m compileall -q people_gator processing_api user_scripts
```

Full model-backed processing needs the selected models and configuration. Regular unit tests should use controlled model and HTTP responses.

## How to write new tests

1. Add a focused `tests/test_*.py` module with clear expected behavior.
2. Put synthetic page images, ALTO/PAGE XML, and metadata JSON in `tests/resources/`. Match image names to page IDs.
3. Stub YOLO inference, LLM Responses requests, and PeopleGatorApp/DocAPI HTTP traffic. Use temporary directories for results.
4. Assert the resulting Python objects and exported XML/API data. For XML, check namespaces, relationships and coordinate values rather than whitespace or generated timestamps.
5. Include empty, ambiguous and failure cases; add a regression test for each bug.
6. Run the focused tests and the available full suite; record executed commands and outcomes in the pull request.

See [Output formats](OUTPUT_FORMATS.md) for representative ALTO and PAGE annotations.
