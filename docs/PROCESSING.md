# Processing pipeline

PeopleGator analyses scanned pages using a configurable sequence of processing engines. The processing pipeline detects face occurrences, proposes associated person names from visual/textual context, resolves candidate people through an API, and enriches document XML.

## Inputs and document model

`user_scripts/parse_folder.py` accepts an INI file (`--config`), page images (`--input-image-path`), source layout in ALTO XML (`--input-alto-path`) or PAGE XML (`--input-xml-path`), and optional JSON metadata (`--input-metadata-path`). Page images are located as `<page-id>.jpg`. `PeopleGatorDocument` builds its page list from the source XML and attaches images and optional document metadata.

Document metadata may include `document.id`, `document.name`, `document.library` and `pages_metadata`. The first three fields identify records during PeopleGatorApp export.

## Configured engines (current implementation)

`DocumentParser` processes `[ENGINE_*]` sections in INI order. Each section selects an implementation through `METHOD`:

| METHOD | Processing step |
| --- | --- |
| `FACE_DETECTION_YOLO` | Detects faces in source-region image crops with a configured YOLO model; creates face regions with bounding boxes, five landmarks and confidence. |
| `LLM_FACE_ASSIGNMENT` | Uses a face crop, contextual image, nearby OCR and optional AnnoPage caption to propose a normalized name for each face. |
| `LLM_BATCH_FACE_ASSIGNMENT` | Processes groups of faces sharing a source region; offers `sequential`, `page_parallel` and `document_parallel` modes and a configurable `max_people` limit. |
| `ENTITY_MATCHING` | Searches person entities through the PeopleGatorApp API, disambiguates candidates using an LLM and assigns or creates person records. |

The detector supports `MODEL_PATH`, `DETECTION_THRESHOLD`, `IMAGE_SIZE`, `AGNOSTIC_NMS` and a source-region `categories` filter. It maps crop-relative bounding boxes and eye/nose/mouth keypoints to full-page coordinates.

LLM-based stages use a configured OpenAI-compatible Responses endpoint, prompt-template JSON, optional response schemas, and structured return models. The prompt may contain text recognized by OCR and an AnnoPage caption identifying a person near a photograph.

## Entity and occurrence terminology

The system design distinguishes **Entity** (a person) from **occurrence** (an appearance of that person in a document). An image occurrence is represented by a face region; a textual occurrence is a name/span on the page. An entity can be associated with multiple occurrences.

The intended entity lifecycle includes identification of occurrences, linking them to existing person entities or creating provisional entities, and librarian verification/correction. The broader database model includes `Entity`, `Face`, `DocumentMention`, `PageMention` and `Source`.

**Current behavior:** `PeopleGatorFaceRegionLayout` and `PeopleGatorPageIdentity` store faces, their proposed names and optional PeopleGatorApp IDs. `PeopleGatorDocument` includes text-entity mention/cluster data structures inherited from the supplied layouts.

**Planned processing:** recognize person-name occurrences across OCR text, associate mentions and detected faces with person entities, use face embeddings for cross-document similarity and incorporate librarian-verified identity assignments. The implementation currently uses names and contextual LLM judgments in the `ENTITY_MATCHING` engine.

## Matching and verification

With a proposed name, `ENTITY_MATCHING` searches the app API. One result is accepted directly; multiple results are disambiguated with contextual LLM input. When the resulting candidate list is empty, the current engine creates a new person entity. Faces with no proposed name retain their unassigned identity state.

The intended database supports provisional entities originating in processing and reviewed/verified entities managed by librarians. Agent-authored changes to the matching policy should include precise confidence and verification requirements in the issue and regression tests for ambiguous names.

## Local and managed execution

A detection-only example INI:

~~~ini
[ENGINE_FACE_DETECTION]
METHOD = FACE_DETECTION_YOLO
MODEL_PATH = /absolute/path/to/compatible-face-model.pt
~~~

Run local processing after preparing dependencies, input pages and a compatible detector:

~~~bash
python -m user_scripts.parse_folder \
  --config ./local-config.ini \
  --input-image-path ./sample/images \
  --input-alto-path ./sample/alto \
  --output-alto-path ./output/alto \
  --device cpu
~~~

Use `--input-xml-path` and `--output-xml-path` for PAGE XML. `--output-render-path` produces annotated preview images.

The DocAPI-based client submits a job with images/layout/metadata; the worker obtains inputs and runs the processing command. `DocumentParser` performs optional PeopleGatorApp import before the engines and export after them, controlled by `--import-from-app`, `--export-to-app` and `[DB_API]`.

## Planned processing improvements

The complete workflow will verify subprocess exit status and result delivery, propagate API/storage failures, support repeatable imports and exports, and regenerate XML after identity corrections. See [Architecture](ARCHITECTURE.md#planned-correction-and-re-export-flow), [Output formats](OUTPUT_FORMATS.md) and [Testing](TESTING.md).
