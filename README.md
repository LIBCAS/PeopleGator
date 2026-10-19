# PeopleGator

PeopleGator is a **Python document-processing tool** for detecting faces on scanned document pages, proposing person names from image/text context, and connecting them with person identities in [PeopleGatorApp](https://github.com/DCGM/PeopleGatorApp).

## Key features

- **Face detection:** detect faces in graphical regions of digitized pages using a configurable YOLO model, recording face coordinates, confidence and facial landmarks.
- **Person identification:** use page imagery, nearby OCR text and available captions to propose person names with single-face or batch LLM processing.
- **Entity matching:** resolve proposed names against person records through the PeopleGatorApp API and associate detected faces with identities.
- **Document annotation:** enrich ALTO XML or PAGE XML with face regions, identity references and processing metadata, and optionally generate annotated page previews.
- **Database integration:** import face records from PeopleGatorApp and export processed document/page/face data using its HTTP API.
- **Job processing:** provide a DocAPI-based processing API, worker and CLI client for submitting document jobs and retrieving results.

**Development direction:** support named-person occurrences in OCR text, face-embedding-based matching, and re-export of annotations after librarians correct person assignments in PeopleGatorApp. The [Processing](docs/PROCESSING.md) guide distinguishes the active engines from these planned stages.

## Repository structure

```text
people_gator/
├── core/             # Document models, layouts, XML serialization, app API access
├── engines/          # Face detection, LLM face assignment, entity matching
├── enums/            # Processing mode definitions
└── globals.py        # Project metadata and XML namespaces
processing_api/       # DocAPI processing API, client and worker
user_scripts/         # Local document-folder processing CLI
docs/                 # Architecture, processing, output and testing guides
AGENTS.md             # Instructions for AI-assisted development
README.md             # Project overview and usage
```

The `people_gator/core/layout.py` and `people_gator/core/document_parser.py` modules are the main starting points for understanding document representations and engine orchestration.

## Architecture overview

The processing path combines client submission, managed worker execution, configurable document analysis and persistence of person occurrences:

```text
                         PeopleGator Client
                       (images + ALTO/PAGE)
                                 |
                         Processing API
                            (DocAPI)
                                 |
                               Worker
                                 |
                 PeopleGator document processing
                    |        |         |
                 Face     LLM name   Entity
               detection  assignment matching
                                 |
                         PeopleGatorApp API
                                 |
                         Person/face database
                                 |
                    ALTO/PAGE XML results
                          via API/client
```

The local CLI can run the processing pipeline directly. The DocAPI-based API, worker and client provide asynchronous job submission, input transfer and result retrieval. PeopleGatorApp stores processed faces and identities, making them available for subsequent documents and manual review.

**Planned re-export workflow:** after a librarian corrects identities in PeopleGatorApp, the client requests a new processing job; the pipeline imports the updated assignments and regenerates ALTO annotations from the supplied source document. This workflow is described in the [system design document](docs/ARCHITECTURE.md#planned-correction-and-re-export-flow) and is being developed incrementally.

See [Architecture](docs/ARCHITECTURE.md) for module boundaries and data flow.

## Documentation

- [AGENTS.md](AGENTS.md) — instructions for Codex and other coding agents.
- [Architecture](docs/ARCHITECTURE.md) — modules, data flow and service boundaries.
- [Processing](docs/PROCESSING.md) — input assumptions, engines and configuration.
- [Output formats](docs/OUTPUT_FORMATS.md) — XML/app output and current gaps.
- [Testing](docs/TESTING.md) — planned deterministic test strategy.

## Related projects

PeopleGator uses OCR layout primitives from [pero-ocr](https://github.com/DCGM/pero-ocr) and the page-layout/metadata abstractions of [AnnoPage](https://github.com/LIBCAS/AnnoPage). [PeopleGatorApp](https://github.com/DCGM/PeopleGatorApp) owns the separate application/database API; [DocAPI](https://github.com/DCGM/DocAPI) manages jobs.

## Installation

Run PeopleGator in a Python environment containing compatible versions of AnnoPage, pero-ocr and DocAPI, together with the Python imaging, XML, inference and LLM libraries used by the selected engines. Prepare a compatible face-detection model and an INI configuration for the processing stages you intend to run. A reproducible package manifest and pinned installation guide are planned development tasks.

After preparing the environment, inspect the local CLI options from the repository root:

~~~bash
python -m user_scripts.parse_folder --help
~~~

## Example local invocation

Provide a model returning face boxes and five landmarks and a local INI file:

~~~ini
[ENGINE_FACE_DETECTION]
METHOD = FACE_DETECTION_YOLO
MODEL_PATH = /absolute/path/to/compatible-face-model.pt
~~~

Provide page JPEGs named `<page-id>.jpg` and corresponding source layout XML:

~~~bash
python -m user_scripts.parse_folder \
  --config ./local-config.ini \
  --input-image-path ./sample/images \
  --input-alto-path ./sample/alto \
  --output-alto-path ./output/alto \
  --device cpu
~~~

For PAGE XML use `--input-xml-path` and `--output-xml-path`. `--output-render-path` adds visual annotations. App import/export requires separate `[DB_API]` configuration and appropriate document metadata; see [Processing](docs/PROCESSING.md). The example illustrates the current CLI arguments; adapt the paths and model configuration for your local data.
