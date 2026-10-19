# Architecture

PeopleGator provides the document-processing component of a system for recognizing people in digitized documents. It analyses page imagery and existing OCR/layout information, associates detected occurrences with person entities, and produces annotations for downstream digital-library use.

This guide draws on the current repository and the attached PeopleGator system design. The sections marked **Current implementation** describe code in this repository; sections marked **Planned** describe the processing workflow proposed in the design.

## Processing architecture

```text
Client (page images, ALTO/PAGE XML, document metadata)
          |
PeopleGator Processing API (DocAPI)
          |
Worker (job polling, inputs, engine configuration)
          |
PeopleGatorDocument + DocumentParser
          |---- configured face detector
          |---- LLM face/name assignment
          |---- person entity matching
          |
PeopleGatorApp / DB API <----> person + face records
          |
ALTO/PAGE XML and optional rendered pages
          |
Worker -> Processing API -> Client
```

**Current implementation:** The CLI in `user_scripts/parse_folder.py` loads page layouts and images, invokes `DocumentParser`, then writes ALTO XML, PAGE XML and optional visualizations. The `processing_api/` directory integrates DocAPI's server, worker and client wrappers. The worker starts the processing program for a retrieved job. The application adapter communicates with PeopleGatorApp over authenticated HTTP.

**Planned processing lifecycle:** the client submits document pages and OCR XML as a job, the worker obtains the data and configured models, and it returns processed XML and additional results through the Processing API. Person/face annotations are also stored via the PeopleGatorApp API and support analysis of subsequent documents.

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

## Planned correction and re-export flow

The system design describes a feedback loop:

1. Process page images and ALTO and store detected occurrences with provisional identity assignments.
2. A librarian reviews and corrects identities using PeopleGatorApp.
3. The client submits a re-export request and supplies the relevant original ALTO.
4. Processing imports the corrected associations through the app API and writes updated ALTO annotations.
5. The Processing API returns the regenerated results to the client.

The current `DocumentParser.process_document()` provides the underlying `import_from_app` and `export_to_app` switches. Completing the entire re-export job path, including reliable round-tripping of face metadata, is a planned integration task.

## Processing and delivery milestones

Current face processing uses source regions from ALTO/PAGE XML; engine sections determine stage order. The intended pipeline also covers person mentions extracted from text, embeddings for comparing face occurrences with stored faces, and reuse of reviewed associations. The PDF describes ALTO XML as an exchange format for Kramerius/ČDK and describes a future searchable, authority-enriched person database; these are downstream integration requirements.

See [Output formats](OUTPUT_FORMATS.md) for the serialized contracts and [Testing](TESTING.md) for validation priorities.
