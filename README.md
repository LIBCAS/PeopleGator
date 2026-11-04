# PeopleGator

PeopleGator is a **Python document-processing tool** for detecting faces on scanned document pages, proposing person names from image/text context, and connecting them with person identities in [PeopleGatorApp](https://github.com/DCGM/PeopleGatorApp).

## Key features

- **Face detection:** detect faces in graphical regions of digitized pages using a configurable YOLO model, recording face coordinates, confidence and facial landmarks.
- **Person identification:** use page imagery, nearby OCR text and available captions to propose person names with single-face or batch LLM processing.
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
- [Output formats](docs/OUTPUT_FORMATS.md) — XML/app output and current gaps.
- [Testing](docs/TESTING.md) — planned deterministic test strategy.

## Related projects

PeopleGator uses OCR layout primitives from [pero-ocr](https://github.com/DCGM/pero-ocr) and the page-layout/metadata abstractions of [AnnoPage](https://github.com/LIBCAS/AnnoPage). [PeopleGatorApp](https://github.com/DCGM/PeopleGatorApp) owns the separate application/database API; [DocAPI](https://github.com/DCGM/DocAPI) manages jobs.

## Installation

Use Python 3.10 or newer and Git (needed for the pinned AnnoPage and pero-ocr dependencies). From a checkout of this repository, create an environment and install the base package for local processing and entity merging:

~~~bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
~~~

The base package includes the processing engines and their imaging, XML, inference and LLM dependencies. Install optional DocAPI components as needed:

~~~bash
python -m pip install '.[api]'       # processing API server
python -m pip install '.[client]'    # job submission and result retrieval
python -m pip install '.[worker]'    # worker, including local processing
python -m pip install '.[full]'      # all application components
python -m pip install -e '.[full,test]'  # editable development install and test/build tools
~~~

Each DocAPI extra currently installs the same pinned DocAPI distribution, which supplies the server, client and worker wrappers. The `test` extra can also be combined with the base package (`pip install -e '.[test]'`). Upstream Git dependencies are pinned to commits; published dependencies use compatible requirements rather than a complete lock file. The selected PyTorch build must support your Python version and CPU/CUDA platform. OpenCV may require system graphics libraries on Linux.

Prepare a compatible face/keypoint model and an INI configuration for the stages you intend to run. Models, prompts, credentials, the PeopleGatorApp service, and the DocAPI server's database configuration are supplied separately; installing an extra does not start a service.

Installed commands delegate to the existing `main()` functions and retain the module CLI arguments:

| Command | Existing module | Installation |
| --- | --- | --- |
| `peoplegator` | `user_scripts.parse_folder` | base |
| `peoplegator_merge_document_entities` | `user_scripts.merge_document_entities` | base |
| `peoplegator_api` | `processing_api.api` | `api` or `full` |
| `peoplegator_client` | `processing_api.client` | `client` or `full` |
| `peoplegator_worker` | `processing_api.worker` | `worker` or `full` |

All command wrappers are installed with the base package; API commands require their corresponding extra at runtime. `peoplegator_api` starts DocAPI using environment configuration and has no `--help` interface. The other commands support `--help`.

After preparing the environment, inspect the local CLI options from the repository root:

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
