# Processing

PeopleGator runs configured engines over page images and OCR/layout information. `DocumentParser` constructs the engines from the `[ENGINE_*]` sections of an INI file, in section order.

## Current engines

Each engine is configured in an `[ENGINE_*]` INI section. **Required** means necessary for the documented processing workflow; some required values are used at runtime rather than validated when the configuration is loaded. **—** means no default is defined in the code. Shared LLM settings are repeated so each engine's table is complete.

### 1. `FACE_DETECTION_YOLO`

Detects faces in selected source-region images and records bounding boxes, confidence, and five landmarks (eyes, nose, and mouth corners).

| name | required | default value | description |
| --- | --- | --- | --- |
| `METHOD` | True | — | Selects `FACE_DETECTION_YOLO`. |
| `MODEL_PATH` | True | — | Path to a compatible YOLO face/keypoint model. |
| `DETECTION_THRESHOLD` | False | `0.2` | Minimum face detection confidence. |
| `IMAGE_SIZE` | False | `640` | Image size used during YOLO inference. |
| `AGNOSTIC_NMS` | False | `False` | Enables class-agnostic non-maximum suppression. |
| `categories` | False | `None` | Source-region categories to process; `None` uses all eligible regions. |

### 2. `LLM_FACE_ASSIGNMENT`

Proposes a normalized person name for each detected face using its crop, marked context image, nearby OCR text, and available captions.

| name | required | default value | description |
| --- | --- | --- | --- |
| `METHOD` | True | — | Selects `LLM_FACE_ASSIGNMENT`. |
| `api_url` | True | — | OpenAI-compatible Responses API endpoint. |
| `api_key` | True | — | API authentication key. |
| `model_name` | True | — | LLM model used for assignment. |
| `prompt_template_path` | True | — | JSON file defining the system/user Jinja2 prompt templates. |
| `json_schema_path` | False | `None` | Optional JSON response schema. |
| `reasoning_effort` | False | `low` | Reasoning effort requested from the model. |
| `max_output_tokens` | False | `1000` | Maximum response token count. |
| `vertical_offset` | False | `0` | Vertical context margin in multiples of median OCR line height. |
| `horizontal_offset` | False | `0` | Horizontal context margin in multiples of median OCR line height. |

### 3. `LLM_BATCH_FACE_ASSIGNMENT`

Assigns names to groups of faces in the same source region and supports sequential or parallel LLM requests.

| name | required | default value | description |
| --- | --- | --- | --- |
| `METHOD` | True | — | Selects `LLM_BATCH_FACE_ASSIGNMENT`. |
| `api_url` | True | — | OpenAI-compatible Responses API endpoint. |
| `api_key` | True | — | API authentication key. |
| `model_name` | True | — | LLM model used for batch assignment. |
| `prompt_template_path` | True | — | JSON file defining the system/user Jinja2 prompt templates. |
| `json_schema_path` | False | `None` | Optional JSON response schema. |
| `reasoning_effort` | False | `low` | Reasoning effort requested from the model. |
| `max_output_tokens` | False | `1000` | Maximum response token count. |
| `max_people` | False | `3` | Maximum number of faces per source region to assign. |
| `processing_mode` | False | `sequential` | `sequential`, `page_parallel`, or `document_parallel` request execution. |
| `vertical_offset` | False | `0` | Vertical context margin in multiples of median OCR line height. |
| `horizontal_offset` | False | `0` | Horizontal context margin in multiples of median OCR line height. |

### 4. `ENTITY_MATCHING`

Searches PeopleGatorApp for a person using a proposed name. Selects a single match, uses the LLM to disambiguate multiple candidates, and requests a new person record when no candidate remains.

| name | required | default value | description |
| --- | --- | --- | --- |
| `METHOD` | True | — | Selects `ENTITY_MATCHING`. |
| `api_url` | True | — | OpenAI-compatible Responses API endpoint for disambiguation. |
| `api_key` | True | — | API authentication key. |
| `model_name` | True | — | LLM model used to disambiguate people. |
| `prompt_template_path` | True | — | JSON file defining the system/user Jinja2 prompt templates. |
| `json_schema_path` | False | `None` | Optional JSON response schema. |
| `reasoning_effort` | False | `low` | Reasoning effort requested from the model. |
| `max_output_tokens` | False | `1000` | Maximum response token count. |

**Database dependency:** `ENTITY_MATCHING` also needs a separate `[DB_API]` section to connect to PeopleGatorApp. `DocumentParser` skips entity matching when that service is unavailable.

The LLM settings come from `LLMBasedEngine` in `people_gator/engines/llm.py`. Run detection before face assignment, and face assignment before entity matching when using all three stages.

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
