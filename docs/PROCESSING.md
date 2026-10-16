# Processing pipeline

This is a description of the **current implementation**, not a guarantee of face identification accuracy.

## Inputs

`user_scripts/parse_folder.py` accepts:
- `--config`: INI file specifying `ENGINE_*` sections;
- `--input-image-path`: directory containing `<page-id>.jpg`;
- **either** `--input-alto-path` (ALTO XML) **or** `--input-xml-path` (PAGE XML), providing the page layouts;
- optional `--input-metadata-path`: JSON containing `document.id`, `document.name`, `document.library` and/or `pages_metadata`.

The XML layout is essential to discover document pages and source regions. The metadata fields `document.id`, `document.name` and `document.library` are required for the current PeopleGatorApp export path.

## Engine execution

`DocumentParser` instantiates `[ENGINE_*]` INI sections in their listed order. Each engine's `METHOD` determines its implementation:

| METHOD | What it currently does |
| --- | --- |
| `FACE_DETECTION_YOLO` | Runs a configured YOLO model over selected source-region crops, converts boxes/landmarks to page coordinates, and creates `PeopleGatorFaceRegionLayout` entries. |
| `LLM_FACE_ASSIGNMENT` | Uses one face crop, marked context image, nearby OCR text and optional AnnoPage caption to propose a normalized person name. |
| `LLM_BATCH_FACE_ASSIGNMENT` | Groups faces by source region and asks the LLM about multiple faces together. Supports `sequential`, `page_parallel`, `document_parallel`; skips source regions with more than `max_people` faces. |
| `ENTITY_MATCHING` | Searches the PeopleGatorApp person API using a proposed name, asks the LLM to distinguish multiple candidates, and assigns or creates an entity. |

Detection requires a compatible model returning bounding boxes and five landmark points (left/right eyes, nose, left/right mouth corners). Config options include `MODEL_PATH`, `DETECTION_THRESHOLD`, `IMAGE_SIZE`, `AGNOSTIC_NMS`, and a source-region `categories` filter. Faces are initially unassigned.

Assignment engines use an OpenAI-compatible Responses API via `people_gator/engines/llm.py`. Relevant options include `api_url`, `api_key`, `model_name`, `prompt_template_path`, optional `json_schema_path`, and generation settings. Visual context is derived from the face and parent/source region; text and captions are used when available.

**Identity policy currently implemented:** no normalized name means no entity lookup. One search result is selected; multiple are LLM-disambiguated. If the resulting candidate list is empty (including failed/declined disambiguation), the engine tries to **create a new person**. A proposed name therefore is not verified identity evidence. Changes to this risky behavior require an explicit issue, acceptance criteria and tests.

## Optional app import/export

If `[DB_API]` is configured, `DatabaseApiService` uses the PeopleGatorApp HTTP API. `--import-from-app` imports existing faces **before** engines. `--export-to-app` exports document/page/face data **after** engines. Without the config, those optional steps are skipped. See [Output formats](OUTPUT_FORMATS.md) for payload and vector limitations.

## Example: local detection-only run

The repository does not currently include packaging metadata, a model checkpoint, or a ready-to-use sample INI. After installing dependencies and providing your own compatible model, a minimal config has this shape:

~~~ini
[ENGINE_FACE_DETECTION]
METHOD = FACE_DETECTION_YOLO
MODEL_PATH = /absolute/path/to/compatible-face-model.pt
~~~

~~~bash
python -m user_scripts.parse_folder \
  --config ./local-config.ini \
  --input-image-path ./sample/images \
  --input-alto-path ./sample/alto \
  --output-alto-path ./output/alto \
  --device cpu
~~~

To use PAGE instead, select `--input-xml-path` and `--output-xml-path`. Optional annotated renderings use `--output-render-path`. The example describes the CLI, **not a verified turnkey installation**.

## Failure behavior to address in later changes

Missing/mismatched source regions, invalid metadata, unavailable model/provider or malformed provider responses can disrupt or degrade processing. App import/export currently logs some failures and continues. The DocAPI worker currently returns an OK result without checking the spawned process's exit status. Do not assume atomic export, safe retries, or successful job propagation until these are tested or fixed.
