# Processing

PeopleGator runs configured engines over page images and OCR/layout information. `DocumentParser` constructs the engines from the `[ENGINE_*]` sections of an INI file, in section order.

## Current engines

1. **`FACE_DETECTION_YOLO`** — Detects faces in selected source-region images and records bounding boxes, confidence, and five landmarks (eyes, nose, and mouth corners).
   - Required: `METHOD = FACE_DETECTION_YOLO` and `MODEL_PATH` (compatible YOLO face/keypoint model).
   - Optional: `DETECTION_THRESHOLD` (default `0.2`), `IMAGE_SIZE` (default `640`), `AGNOSTIC_NMS` (default `False`), `categories` (source-region filter).

2. **`LLM_FACE_ASSIGNMENT`** — Proposes a normalized person name for each detected face from the face crop, marked context image, nearby OCR text, and any available caption.
   - Required: `METHOD = LLM_FACE_ASSIGNMENT` and LLM connection/prompt settings below.
   - Optional: `vertical_offset`, `horizontal_offset` (default `0`; multiples of median OCR line height used to extend context).

3. **`LLM_BATCH_FACE_ASSIGNMENT`** — Assigns names to groups of faces in the same source region; supports concurrent requests.
   - Required: `METHOD = LLM_BATCH_FACE_ASSIGNMENT` and LLM settings.
   - Optional: `max_people` (default `3`; larger groups are skipped), `processing_mode` (`sequential`, `page_parallel`, or `document_parallel`; default `sequential`), `vertical_offset`, `horizontal_offset`.

4. **`ENTITY_MATCHING`** — Searches PeopleGatorApp for a person using the proposed name. A single result is selected; multiple results are disambiguated with the LLM. If no candidate remains, the current engine requests creation of a new person.
   - Required: `METHOD = ENTITY_MATCHING`, LLM settings, and `[DB_API]` for the person database connection.

### Shared LLM settings

These settings are read by `LLMBasedEngine` in `people_gator/engines/llm.py`.

| INI setting | Purpose |
| --- | --- |
| `api_url`, `api_key`, `model_name` | OpenAI-compatible Responses endpoint, authentication, model |
| `prompt_template_path` | JSON file with system/user Jinja2 prompt templates |
| `json_schema_path` | Optional JSON output schema |
| `reasoning_effort` | Model reasoning setting; default `low` |
| `max_output_tokens` | Output token limit; default `1000` |

Run detection before face assignment, and face assignment before entity matching when using all three stages.

## Processing script

`user_scripts/parse_folder.py` loads the configuration and document, invokes `DocumentParser`, and saves requested outputs. Images are stored as `<page-id>.jpg` alongside matching source ALTO or PAGE XML files.

| CLI argument | Purpose |
| --- | --- |
| `--config` | **Required** INI processing configuration |
| `--input-image-path` | Input page-image directory |
| `--input-alto-path` / `--input-xml-path` | Input ALTO / PAGE XML directory (choose one) |
| `--input-metadata-path` | Optional JSON document metadata |
| `--output-alto-path` / `--output-xml-path` | Output ALTO / PAGE XML directories |
| `--output-render-path` | Optional annotated JPEG directory |
| `--import-from-app` / `--export-to-app` | Import stored annotations before processing / export results after processing |
| `--device`, `--gpu-id` | CPU or GPU choice and optional GPU index; CPU is the default |
| `--logging-level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Example

Provide an INI file with a compatible face/keypoint model:

```ini
[ENGINE_FACE_DETECTION]
METHOD = FACE_DETECTION_YOLO
MODEL_PATH = /path/to/face-model.pt
```

Process page images and ALTO XML:

```bash
python -m user_scripts.parse_folder \
  --config ./config.ini \
  --input-image-path ./input/images \
  --input-alto-path ./input/alto \
  --output-alto-path ./output/alto \
  --device cpu
```

Use `--input-xml-path` and `--output-xml-path` for PAGE XML. Optional metadata JSON may contain `document.id`, `document.name`, `document.library`, and `pages_metadata`; the first three are used for PeopleGatorApp export.

The DocAPI-based client and worker in `processing_api/` offer the job-based processing path. See [Architecture](ARCHITECTURE.md) and [Output formats](OUTPUT_FORMATS.md).
