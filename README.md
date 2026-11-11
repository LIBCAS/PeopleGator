# PeopleGator

PeopleGator is a **Python document-processing tool** for detecting faces on scanned document pages, proposing person names from image/text context, and connecting them with person identities in [PeopleGatorApp](https://github.com/DCGM/PeopleGatorApp).

## Key features

- **Face detection:** detect faces in graphical regions of digitized pages using a configurable YOLO model, recording face coordinates, confidence and facial landmarks.
- **Person identification:** use page imagery, nearby OCR text and available captions to propose person names with single-face or batch LLM processing.
- **Text entity clustering:** group source-mapped OCR mentions across a document using fuzzy candidates and externally prompted LLM disambiguation, before app linking. See [configuration and contracts](docs/PROCESSING.md#document-text-entity-clustering-text_entity_clustering).
- **Entity matching:** resolve proposed names against person records through the PeopleGatorApp API and associate detected faces with identities.
- **Document annotation:** enrich ALTO XML or PAGE XML with face regions, identity references and processing metadata, and optionally generate annotated page previews.
- **Database integration:** import face records from PeopleGatorApp and export processed document/page/face data using its HTTP API.
- **Job processing:** provide a DocAPI-based processing API, worker and CLI client for submitting document jobs and retrieving results.

## Repository structure

```text
people_gator/
├── core/             # Document models, layouts, XML serialization, app API access
├── engines/          # Face detection, LLM face assignment, entity matching
├── enums/            # Enum definitions
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
                         (Face detection, 
                        LLM name assignment, 
                          Entity matching)
                                 |
                         PeopleGatorApp API
                                 |
                         Person/face database
                                 |
                        ALTO/PAGE XML results
                           via API/client
```

The local CLI can run the processing pipeline directly. The DocAPI-based API, worker and client provide asynchronous job submission, input transfer and result retrieval. PeopleGatorApp stores processed faces and identities, making them available for subsequent documents and manual review.

See [Architecture](docs/ARCHITECTURE.md) for module boundaries and data flow.

## Documentation

- [AGENTS.md](AGENTS.md) — instructions for Codex and other coding agents.
- [Creating issues](docs/ISSUE_WORKFLOW.md) — turning a plain-language request into a reviewable GitHub issue.
- [Architecture](docs/ARCHITECTURE.md) — modules, data flow and service boundaries.
- [Processing](docs/PROCESSING.md) — input assumptions, engines and configuration.
- [Example pipeline INI](resources/config.example.ini) and [prompt resources](resources/README.md) —
  explicit per-engine prompt paths, including the supplied face and clustering prompts.
- [Output formats](docs/OUTPUT_FORMATS.md) — XML/app output and current gaps.
- [Testing](docs/TESTING.md) — planned deterministic test strategy.

## Related projects

PeopleGator uses OCR layout primitives from [pero-ocr](https://github.com/DCGM/pero-ocr) and the page-layout/metadata abstractions of [AnnoPage](https://github.com/LIBCAS/AnnoPage). [PeopleGatorApp](https://github.com/DCGM/PeopleGatorApp) owns the separate application/database API; [DocAPI](https://github.com/DCGM/DocAPI) manages jobs.

## Installation

Use Python 3.10 or newer and Git (needed for the pinned AnnoPage and pero-ocr dependencies). From a checkout of this repository, create an environment and explicitly select the components you need. For local processing and entity merging, install the `tool` extra:

~~~bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install '.[tool]'
~~~

The base package (`pip install .`) installs the Python modules and command wrappers without runtime dependencies. Select optional components as needed:

~~~bash
python -m pip install '.[tool]'      # local processing and entity merging
python -m pip install '.[api]'       # processing API server
python -m pip install '.[client]'    # job submission and result retrieval
python -m pip install '.[worker]'    # DocAPI worker wrapper
python -m pip install '.[full]'      # all application components
python -m pip install -e '.[full,test]'  # editable development install and test/build tools
~~~

The `client`, `api` and `worker` extras install only the pinned DocAPI distribution and its transitive dependencies. They do not install the PeopleGator processing stack (AnnoPage, pero-ocr, PyTorch, Ultralytics or LLM libraries). DocAPI itself currently requires NumPy and OpenCV, so those remain transitive dependencies. The `tool` extra provides all local processing dependencies without DocAPI; `full` combines both sets. To execute local processing jobs from a worker, install `.[worker,tool]` or `.[full]` so the worker subprocess has the processing dependencies. The `test` extra installs only test/build tooling and can be combined with any application extra.

Upstream Git dependencies are pinned to commits; published dependencies use compatible requirements rather than a complete lock file. The selected PyTorch build must support your Python version and CPU/CUDA platform. OpenCV may require system graphics libraries on Linux.

Prepare a compatible face/keypoint model and an INI configuration for the stages you intend to run. Models, prompts, credentials, the PeopleGatorApp service, and the DocAPI server's database configuration are supplied separately; installing an extra does not start a service.

Installed commands delegate to the existing `main()` functions and retain the module CLI arguments:

| Command | Existing module | Installation |
| --- | --- | --- |
| `peoplegator` | `user_scripts.parse_folder` | `tool` or `full` |
| `peoplegator_merge_document_entities` | `user_scripts.merge_document_entities` | `tool` or `full` |
| `peoplegator_api` | `processing_api.api` | `api` or `full` |
| `peoplegator_client` | `processing_api.client` | `client` or `full` |
| `peoplegator_worker` | `processing_api.worker` | `worker` or `full` |

All command wrappers are installed with the base package; running each command requires the extra listed above. `peoplegator_api` starts DocAPI using environment configuration and has no `--help` interface. The other commands support `--help`.

With the `tool` extra installed, inspect the local CLI options:

~~~bash
peoplegator --help
peoplegator_merge_document_entities --help
~~~

The existing `python -m user_scripts.parse_folder` invocation remains available. See [Testing](docs/TESTING.md) for package build and validation commands.

## Example local invocation

Provide a model returning face boxes and five landmarks and a local INI file:

~~~ini
[ENGINE_FACE_DETECTION]
METHOD = FACE_DETECTION_YOLO
MODEL_PATH = /absolute/path/to/compatible-face-model.pt
~~~

For the text/person pipeline, adapt [config.example.ini](resources/config.example.ini):
provide service settings, review the supplied prompts, and remove unused engine
sections (choose single or batch face assignment). Then run
`python -m user_scripts.parse_folder --config ./resources/config.example.ini ...` with the
input/output arguments below. Prompt paths resolve from the INI directory and
may point to any valid external JSON file without code changes. Deploy that INI
and its referenced resources together, including on worker hosts; installed
wheels do not provision these repository examples automatically.

Provide page JPEGs named `<page-id>.jpg` and corresponding source layout XML:

~~~bash
peoplegator \
  --config ./local-config.ini \
  --input-image-path ./sample/images \
  --input-alto-path ./sample/alto \
  --output-alto-path ./output/alto \
  --device cpu
~~~

For PAGE XML use `--input-xml-path` and `--output-xml-path`. `--output-render-path` adds visual annotations. App import/export requires separate `[DB_API]` configuration and appropriate document metadata; see [Processing](docs/PROCESSING.md). The example illustrates the current CLI arguments; adapt the paths and model configuration for your local data.

For text-only inspection with a configured `TEXT_ENTITY_DETECTION` engine, use:

```bash
python -m user_scripts.detect_text_entities --config ./config.ini --input-alto-path ./sample/alto
```

Use `--input-xml-path` for PAGE XML and `--output-path ./output/entities.json`
to save UTF-8 JSON grouped by source page (including pages with no mentions), containing exact OCR mentions and source spans. See the
[diagnostic CLI contract](docs/PROCESSING.md#standalone-text-detection-inspection-cli)
for configuration, output fields and failure behavior.
