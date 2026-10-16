# Architecture

This document describes **this repository**, `LIBCAS/PeopleGator`, as implemented on `develop`, rather than the complete multi-repository system.

## Purpose and processing flow

PeopleGator enriches digitized pages with face regions and person-identity annotations. It starts with page images and existing ALTO/PAGE document layout; optionally imports existing face records from PeopleGatorApp; runs a configurable sequence of engines; and exports annotated XML, renderings and/or records to PeopleGatorApp.

~~~text
JPEG page images + ALTO/PAGE XML + optional JSON document metadata
                              |
                      PeopleGatorDocument
                              |
               DocumentParser / ENGINE_* pipeline
            optional app import -> engines -> app export
                              |
           ALTO XML / PAGE XML / optional rendered JPEG
~~~

`DocumentParser.load_engines()` loads `ENGINE_*` sections **in configuration order**. The usual sequence is face detection, LLM-based face assignment and entity matching, but the order is configured, not hard-coded.

## Responsibilities

| Component | Current responsibility |
| --- | --- |
| `people_gator/core/document_parser.py` | Engine factory, sequential pipeline, optional PeopleGatorApp import/export. |
| `people_gator/core/layout.py` | `PeopleGatorDocument`, `PeopleGatorPageLayout`, face regions, identities, XML import/export and rendering. |
| `people_gator/engines/base.py` | Common engine interfaces. |
| `people_gator/engines/face_detection.py` | YOLO-based face detection on source-region crops, including five facial landmarks. |
| `people_gator/engines/face_assignment.py` | Single/batch LLM name assignment from image and OCR/caption context. |
| `people_gator/engines/entity_matching.py` | Person lookup/disambiguation/creation via PeopleGatorApp API. |
| `people_gator/engines/llm.py` | OpenAI-compatible Responses API prompts and structured results. |
| `people_gator/core/db.py`, `connector.py` | Authenticated HTTP adapter for the PeopleGatorApp API (not direct SQL). |
| `user_scripts/parse_folder.py` | Local folder-processing command. |
| `processing_api/api.py`, `client.py`, `worker.py` | DocAPI-based server, client and job worker entry points. |

## Dependencies and ownership

- [pero-ocr](https://github.com/DCGM/pero-ocr) supplies shared OCR layout and ALTO primitives.
- [AnnoPage](https://github.com/LIBCAS/AnnoPage) supplies page layout, region/metadata abstractions, and upstream non-textual-element context. Its general graphical detection/captioning is not reimplemented here.
- [DocAPI](https://github.com/DCGM/DocAPI) owns processing job/API infrastructure. The worker is a specialized `DocWorkerWrapper` and invokes the processing CLI.
- [PeopleGatorApp](https://github.com/DCGM/PeopleGatorApp) owns the external document, face and person persistence API and the web application. PeopleGator does not own its schema or frontend.
- YOLO and the configured LLM endpoint are model/runtime dependencies, not universal requirements for every pipeline.

## Current boundaries and gaps

Page layouts are loaded from an ALTO or PAGE XML directory; images alone currently do **not** create page layout objects. Face detection works on eligible *existing source regions* (optionally category-filtered), not by generating a full-page region layout itself.

The DocAPI worker calls a `peoplegator` executable, but this repository currently has no `pyproject.toml` or declared console entry point. Packaging must be solved separately. XML face import/round-trip and generated vectors have known limitations; see [Output formats](OUTPUT_FORMATS.md). For configuration and stages see [Processing](PROCESSING.md).
