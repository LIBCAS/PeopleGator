# PeopleGator

PeopleGator is a **Python document-processing tool** for detecting faces on
scanned document pages, proposing person names from image/text context, and
connecting them with person entities in [PeopleGatorApp](https://github.com/DCGM/PeopleGatorApp).
It enriches document data rather than displaying it in a web UI.

The configurable pipeline currently provides YOLO-based face detection,
single/batch LLM-assisted face-name assignment, and entity matching through
the PeopleGatorApp HTTP API. It can write **ALTO XML**, **PAGE XML**, and optional
rendered page images. A [DocAPI](https://github.com/DCGM/DocAPI)-based
API/client/worker layer handles processing jobs.

## Documentation

- [AGENTS.md](AGENTS.md) — instructions for Codex and other coding agents.
- [Architecture](docs/ARCHITECTURE.md) — modules, data flow and service boundaries.
- [Processing](docs/PROCESSING.md) — input assumptions, engines and configuration.
- [Output formats](docs/OUTPUT_FORMATS.md) — XML/app output and current gaps.
- [Testing](docs/TESTING.md) — planned deterministic test strategy.

## Related projects

PeopleGator uses OCR layout primitives from
[pero-ocr](https://github.com/DCGM/pero-ocr) and the page-layout/metadata
abstractions of [AnnoPage](https://github.com/LIBCAS/AnnoPage).
[PeopleGatorApp](https://github.com/DCGM/PeopleGatorApp) owns the separate
application/database API; [DocAPI](https://github.com/DCGM/DocAPI) manages jobs.

Source layout: `people_gator/core/` for documents/XML/application API,
`people_gator/engines/` for detection and assignment, `user_scripts/` for
folder processing, and `processing_api/` for DocAPI integration.

## Installation status

The current checkout **does not yet contain a `pyproject.toml`, requirements
lockfile, bundled model checkpoint or ready-made configuration**. A
reproducible installer is still needed. Running the code requires a Python
environment with the relevant AnnoPage/pero-ocr/DocAPI components and imported
imaging, machine-learning and LLM dependencies installed in compatible versions.
See those upstream repositories and this source code; no version-pinned
installation command is guaranteed by this repository yet.

After setting up the environment, inspect CLI options from the repo root:

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

For PAGE XML use `--input-xml-path` and `--output-xml-path`.
`--output-render-path` adds visual annotations. App import/export requires
separate `[DB_API]` configuration and appropriate document metadata; see
[Processing](docs/PROCESSING.md). The examples describe the interface, **not
a verified turnkey setup**.

## Development status

The tool is actively developed. ALTO face import, PAGE face round-tripping,
export idempotency, worker failure reporting, packaging and automated testing
have known gaps; consult [Output formats](docs/OUTPUT_FORMATS.md) and
[Testing](docs/TESTING.md). These are not assertions that results are
production-ready.

Develop through GitHub issues, branches based on `develop`, tests and
reviewed PRs. The foundational documentation task is
[Issue #9](https://github.com/LIBCAS/PeopleGator/issues/9).

## License

See [LICENSE](LICENSE).
