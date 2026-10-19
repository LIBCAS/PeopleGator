# Architecture

This document describes the current repository and the PeopleGator system design and the core principles guiding its development. The key points for future development are described in [TODO.md](TODO.md). 

## Processing API

TODO: 
- The processing API is based on DocAPI.
- Simple schema client -> API -> worker -> processing -> result -> API -> client.

## Database API

TODO:
- The database API is implemented in PeopleGatorApp.
- The processing tool can import and export data from/to database through the API.

## Processing architecture

TODO:
- Load processing configuration.
- Load document from ALTO/PAGE XML and images.
- Create DocumentParser which takes the document and configuration and orchestrates the processing engines.
- If set, import data from the database API.
- Execute the processing pipeline.
- If set, export data to the database API.
- Save the results to ALTO/PAGE XML.

## Data model

TODO:
- Schema of the data model.

## Repository responsibilities

| Component | Responsibility |
| --- | --- |
| `people_gator/core/document_parser.py` | Configured engine orchestration and application import/export. |
| `people_gator/core/layout.py` | Page/document objects, face-region metadata, ALTO/PAGE I/O and rendering. |
| `people_gator/engines/base.py` | Common processing-engine interfaces. |
| `people_gator/engines/face_detection.py` | YOLO detection in selected image regions; boxes and five landmarks. |
| `people_gator/engines/face_assignment.py` | LLM-supported single/batch naming using images, captions and OCR text. |
| `people_gator/engines/entity_matching.py` | Candidate-entity lookup, LLM disambiguation and creation through the app API. |
| `people_gator/engines/llm.py` | Prompt assembly and structured responses from a configured LLM service. |
| `people_gator/core/db.py`, `connector.py` | Authenticated client for documents, pages, faces and person records. |
| `user_scripts/parse_folder.py` | Local processing entry point. |
| `processing_api/api.py`, `client.py`, `worker.py` | Processing job API, CLI client and worker based on DocAPI. |

## Related software and services

- [pero-ocr](https://github.com/DCGM/pero-ocr) supplies OCR layout primitives, regions and ALTO utilities.
- [AnnoPage](https://github.com/LIBCAS/AnnoPage) supplies page/layout and non-textual-region metadata, including contextual information such as captions.
- [DocAPI](https://github.com/DCGM/DocAPI) supplies job creation, upload/download, server administration, and worker/client wrappers.
- [PeopleGatorApp](https://github.com/DCGM/PeopleGatorApp) provides the person/face database API and the interface for reviewing and correcting assigned identities.
- The configured YOLO and LLM engines supply detection and contextual identification.

The broader data model includes **Entity** (a person), **Face** (a detected face occurrence), **Source** (document/page reference), and planned person mentions in text at page/document level. An occurrence is linked to source material and may refer to an entity. The [Processing](PROCESSING.md) guide describes the matching stages.
