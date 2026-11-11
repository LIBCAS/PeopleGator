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

Resolves document-wide text clusters and already named face identities against
PeopleGatorApp. Retrieval alone never assigns an identity, even with one hit.
The external LLM prompt returns an explicit selection, evidence-supported new
person, or unresolved outcome. See [linking rules and prompt contract](#document-wide-entity-linking-entity_matching).

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

`ENTITY_MATCHING` uses the connection described in [Database API](#database-api).

The LLM settings come from `LLMBasedEngine` in `people_gator/engines/llm.py`. Run detection before face assignment, and face assignment before entity matching when using all three stages.

## Shared LLM prompt configuration and data diagnostics

Every engine inheriting `LLMBasedEngine` requires a nonblank
`PROMPT_TEMPLATE_PATH`: `LLM_FACE_ASSIGNMENT`, `LLM_BATCH_FACE_ASSIGNMENT`,
`ENTITY_MATCHING`, `TEXT_ENTITY_DETECTION` and `TEXT_ENTITY_CLUSTERING`. The base class resolves relative
paths from the INI directory and validates readable UTF-8 JSON, an object root,
and at least one nonblank string `system` and/or `user` template with valid Jinja2
syntax. A role may be absent or a blank string when the other role is usable;
provided roles must be strings. Blank roles are omitted. Invalid configuration
raises `LLMPromptConfigurationError` before prompter construction or processing.
Error messages omit file paths, prompt contents and credentials. This is a shared
requirement, not an optional detector-specific setting.

### Configured resources and deployment

The repository's [prompt resources](../resources/README.md) are examples selected
**only through INI configuration**. The example [config.example.ini](../resources/config.example.ini)
shows text detection → clustering → face detection → single or batch face
assignment → entity matching. Sections execute in insertion order; section names
do not sort the pipeline. Both face-assignment alternatives are shown: remove the
unused section before running. Sections using `{}` placeholders are **not runnable
until complete prompts are provided**; shared validation deliberately rejects them.
Remove any engine section you do not intend to enable (there is no enabled flag).

Every `PROMPT_TEMPLATE_PATH` belongs in its engine's section, alongside the model
and service settings. Paths in the example resolve from the **directory containing
the INI**, so `resources/config.example.ini` refers to `prompts/`. You may replace any
path with another valid populated JSON file, including an absolute path outside
the repository, without code changes. No resource is discovered automatically and
there is no default prompt when the option is absent. All five engines use generated
Pydantic response schemas; the example needs no `JSON_SCHEMA_PATH`.

Deploy the INI and its referenced files together, preserving relative paths, or
update them to accessible absolute paths. Copying the INI to another directory
requires copying its resources or changing its paths. The resources are repository
files, not automatically installed runtime package data: deployments using a wheel
must provision them separately. Replace endpoint, credential and model placeholders
locally and supply the face model separately. See the [CLI example](#example) and
[worker deployment](#docapi-worker).

### Template/data diagnostics

At request preparation, `LLMPrompter` compares supplied `data` keys against the
**union** of undeclared Jinja2 variables in both configured templates. Each missing
placeholder and each unused data key produces a `WARNING` containing only its
name. A key used in either role counts as used; loop-local variables and Jinja2
globals are not falsely reported. For example, `{{ texxt }}` with data containing
`text` warns that `texxt` is missing and `text` is unused.

These diagnostics do not raise, filter data or change rendering. Jinja2's existing
undefined-variable behavior remains in effect (a plain missing placeholder
normally renders as an empty string; expressions retain normal Jinja2 semantics).
Both sequential and parallel requests use this shared preparation path. Variable
values, OCR, rendered prompts and credentials are excluded from these warnings.
Pydantic response classes, generated schemas and response handling are unchanged.

## Reusable text chunking

`people_gator.text.text_chunker_factory(config)` returns a `TextChunker` for use
inside the text detection engine. That engine owns the chunker's lifecycle.
Its existing `[ENGINE_*]` section contains prefixed `CHUNKING_*` options:

```ini
[ENGINE_1]
METHOD = TEXT_ENTITY_DETECTION
# Other NER/LLM options...
CHUNKING_METHOD = LINES
CHUNKING_MAX_CHARS = 4000
CHUNKING_OVERLAP_CHARS = 400
```

The registered `TEXT_ENTITY_DETECTION` engine adapter extracts only `CHUNKING_*`
keys and strips that prefix before calling the independent factory. The engine's
own `METHOD` and other NER/LLM settings must not be forwarded to the factory.
No global `[TEXT_CHUNKING]` or nested `[ENGINE_*.TEXT_CHUNKING]` section is used.
`DocumentParser` and `load_engines()` remain unchanged.

The factory receives a dedicated mapping or ConfigParser section containing only
the **unprefixed** options below. Other consumers can use this contract directly.
Keys are case-insensitive, while the method value is exact. Unknown/duplicate
keys, unsupported methods, noninteger values (including booleans/floats), and
invalid ranges raise `ValueError` naming the option. Integer strings are accepted.

| Option | Default | Meaning |
| --- | --- | --- |
| `METHOD` | `LINES` | Reading-order, line-aware character chunking; `LINE_AWARE` remains an alias. |
| `MAX_CHARS` | `4096` | Positive hard limit on Python Unicode characters, including separators. |
| `OVERLAP_CHARS` | `0` | Canonical text characters repeated between consecutive chunks on the same page; `0 <= OVERLAP_CHARS < MAX_CHARS`. |

Pages retain `document.page_layouts` order. Chunks never cross pages and overlap
resets at each page. Regions use a sorted copy of `page.reading_order` (ID keys
from XML or object keys supported by the layout library), with unlisted regions
last in their original order. Without reading order, existing region order is
retained; ALTO's supported order is the loaded TextBlock order. Lines retain each
region's existing OCR line order. Regions whose category is `text` or `None` are
eligible, matching the existing layout text convention. Other categories,
including image/face regions, are excluded. Empty regions and missing, empty or
non-string transcriptions are skipped. Missing OCR is represented by a
`None` transcription. Layout objects must expose their model fields (`id`,
`regions`, `reading_order`, `category`, `lines`, `transcription` as applicable);
these are accessed directly. The `regions` and `lines` fields are lists; empty
lists represent pages without regions or regions without lines.
Whitespace-only strings are preserved. Region-level
transcription is not used as fallback for absent lines.

The canonical text of each page joins eligible nonempty line transcriptions with
one synthetic `\n`, also between regions. Original whitespace, newlines, Unicode
and hyphenation are preserved verbatim. There is no trailing separator or
separator for a skipped line. Empty pages yield no chunks. The chunker greedily
prefers the last complete line end within the budget that advances beyond the
previous chunk and leaves room for the configured overlap. Otherwise it cuts at
the hard budget, including inside a long line. The next window starts exactly
`OVERLAP_CHARS` before the previous end in canonical page text. This definition
includes synthetic separators: overlap can contain fewer OCR characters than
its configured size. Each chunk adds at least one new canonical character.
With small budgets, chunks can begin/end with a separator or contain only that
separator. Such characters remain explicitly synthetic. No source character is
omitted; all repetition is explained by overlapping windows.

All result records are frozen dataclasses and collections use tuples:

| Record | Fields / semantics |
| --- | --- |
| `TextChunkCollection` | Ordered `chunks` tuple. |
| `TextChunk` | Exact `text`, contiguous document-wide `index` starting at zero, `page_index`, half-open `page_start`/`page_end` in canonical page text, and ordered `mappings`. |
| `ChunkMapping` | Half-open chunk `start`/`end`; `source` address and original transcription `line_start`/`line_end`. Synthetic newlines have `source=None` and both line offsets `None`. Mappings partition the full chunk text. |
| `SourceLine` | `page_id`, `region_id`, `line_id` plus zero-based `page_index`, `region_index`, `line_index` in the **original** document lists. Indices distinguish reused or missing IDs; IDs remain verbatim, including `None`. |
| `SourceSpan` | `source`, `start`, `end` in original OCR text; hashable occurrence key, independent of chunk boundaries. |

`chunk.resolve(start, end)` clips mappings for a substring and retains separators;
returned chunk offsets remain relative to the full chunk. `chunk.source_spans`
returns a tuple of canonical `SourceSpan` keys, excluding separators and merging
adjacent contiguous spans of the same line. Both accept half-open integer offsets
within the chunk (including empty intervals), rejecting invalid offsets with
`ValueError`. Multiline matches yield several source spans without searching OCR
again or guessing coordinates. These keys identify overlap-induced repeats
within the same unchanged document; downstream consumers must retain their own
document identity when comparing across documents. Reordering/editing source
layouts invalidates addresses. Occurrence de-duplication itself is not performed.

Minimal adapter inside the detector, with `engine_config` referring to its
own ConfigParser engine section (ConfigParser lowercases option keys by default):

```python
from people_gator.text import text_chunker_factory

chunker_config = {
    key.upper().removeprefix("CHUNKING_"): value
    for key, value in engine_config.items()
    if key.upper().startswith("CHUNKING_")
}
chunker = text_chunker_factory(chunker_config)
collection = chunker.chunk_document(document)
for chunk in collection.chunks:
    # Send chunk.text to the detector, which returns character offsets.
    start, end = 0, len(chunk.text)
    mappings = chunk.resolve(start, end)  # includes explicit synthetic newlines
    occurrence_key = chunk.source_spans(start, end)  # tuple of OCR spans
```

For the INI example above, the adapter passes
`{"METHOD": "LINES", "MAX_CHARS": "4000", "OVERLAP_CHARS": "400"}`.
Omitted `CHUNKING_*` options use factory defaults: `LINES`, `4096`, and `0`.
An unsupported prefixed option is passed through with its prefix removed so the
factory can reject it, rather than silently ignoring a typo. Passing prefixed
keys or the entire NER section directly to the factory is invalid.

Chunking requires no page images, LLM, database or GPU and does not access image
loading methods, create mentions, or modify existing OCR/annotations. No package
dependencies, XML output or identity contracts change.

## Database API

The `[DB_API]` section configures the PeopleGatorApp database connection. `DatabaseApiService` reads these parameters:

| name | required | default value | description |
| --- | --- | --- | --- |
| `api_url` | True | — | Base URL of the PeopleGatorApp API. |
| `username` | True | — | Account name used to log in to the API. |
| `password` | True | — | Account password used to log in to the API. |

These parameters are needed for the authenticated connection; the code does not define defaults. `DocumentParser` initializes this connection when `[DB_API]` is present. Entity matching and the optional `--import-from-app` / `--export-to-app` stages use it.

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

### `[PARSE_FOLDER]` configuration

The document input/output paths and import/export flags can also be set in the INI file under `[PARSE_FOLDER]`. Use the corresponding uppercase names without the CLI prefix, as in this example:

```ini
[PARSE_FOLDER]
INPUT_IMAGE_PATH = ./input/images
INPUT_ALTO_PATH = ./input/alto
OUTPUT_ALTO_PATH = ./output/alto
IMPORT_FROM_APP = no
EXPORT_TO_APP = no
```

Supported keys are `INPUT_IMAGE_PATH`, `INPUT_ALTO_PATH`, `INPUT_XML_PATH`, `INPUT_METADATA_PATH`, `OUTPUT_ALTO_PATH`, `OUTPUT_XML_PATH`, `OUTPUT_RENDER_PATH`, `IMPORT_FROM_APP`, and `EXPORT_TO_APP`. Choose one input XML format. CLI path options override the corresponding configured values; passing an import/export flag enables it. `--config`, `--device`, `--gpu-id`, and `--logging-level` are CLI-only options in the current script.

The script can therefore run with just `--config ./config.ini` when the remaining processing paths and options are defined in that file.

### Example

Adapt [config.example.ini](../resources/config.example.ini): fill or replace empty prompt
files, remove unused engine sections, choose one face-assignment mode, and
provide service settings and a compatible face/keypoint model. For face
detection alone, a minimal configuration is:

```ini
[ENGINE_FACE_DETECTION]
METHOD = FACE_DETECTION_YOLO
MODEL_PATH = /path/to/face-model.pt
```

Process page images and ALTO XML:

```bash
python -m user_scripts.parse_folder \
  --config ./resources/config.example.ini \
  --input-image-path ./input/images \
  --input-alto-path ./input/alto \
  --output-alto-path ./output/alto \
  --device cpu
```

Use `--input-xml-path` and `--output-xml-path` for PAGE XML. Optional metadata JSON may contain `document.id`, `document.name`, `document.library`, and `pages_metadata`; the first three are used for PeopleGatorApp export.

The DocAPI-based client and worker in `processing_api/` offer the job-based processing path. See [Architecture](ARCHITECTURE.md) and [Output formats](OUTPUT_FORMATS.md).

## DocAPI worker

Install `.[worker,tool]` or `.[full]` to run processing jobs. For example:

```bash
peoplegator_worker --api-url https://docapi.example.org --api-key YOUR_WORKER_KEY \
  --device gpu --gpu-id 0 --logging-level INFO
```

Provision the worker engine's `config.ini` and all referenced prompt files on the
worker host. Relative prompt paths resolve from that engine configuration's
directory, regardless of the worker's working directory; keep the same relative
resource layout or configure accessible absolute paths. Installing PeopleGator or
starting a worker does not download/discover prompts. Fill `{}` placeholders and
supply model files, endpoints and credentials before accepting jobs.

The worker invokes the installed `peoplegator` command with the original engine's `config.ini` and the downloaded image directory. It supplies ALTO or PAGE XML paths according to `job.alto_required` or `job.page_required`, and metadata when `job.meta_json_required` is enabled. Missing optional paths are omitted. Jobs requiring both ALTO and PAGE inputs are rejected before starting the subprocess, preserving the processing CLI's mutually exclusive input contract.

Output arguments come from `job.engine_settings["outputs"]`:

| Engine setting | Processing argument | Directory |
| --- | --- | --- |
| `outputs.alto` | `--output-alto-path` | `result_dir/alto` |
| `outputs.page` | `--output-xml-path` | `result_dir/page` |
| `outputs.renders` | `--output-render-path` | `result_dir/renders` |

For example, `{"outputs": {"alto": true, "page": true, "renders": false}}` requests both XML formats from either supported input format. Disabled or unspecified outputs add no command-line paths; missing or empty engine settings add none. The original configuration is passed through unchanged, so any `[PARSE_FOLDER]` paths in it retain the local CLI behavior described above. Engine configurations intended to select outputs solely through job settings should leave output paths unset in `[PARSE_FOLDER]`.

The worker forwards `--device` and an explicitly supplied integer `--gpu-id` (including zero). Its CLI defaults to `gpu`; direct `PeopleGatorWorker` construction continues to default to `cpu`. The GPU ID defaults to `None` and is omitted unless configured. The subprocess receives the worker logger's effective level through `--logging-level`; the worker CLI defaults to `INFO`.

PeopleGatorApp credentials remain in the engine's `[DB_API]` section. The worker's `--api-url` and `--api-key` authenticate with DocAPI and are separate from that database connection.

The worker reports success to DocAPI only when the `peoplegator` subprocess exits
with code `0`. A non-zero exit code produces a failed worker response identifying
the command, job (when available), and numeric return code. Failure diagnostics
report stdout/stderr character counts at `ERROR`, including empty streams. Raw
child output, command arguments, configuration contents, and worker credentials
are omitted from these diagnostics and the concise failure response.

## Logging

The processing CLI, entity-merging utility, DocAPI client, and worker retain their
`--logging-level` options. `INFO` reports initialization, document/job milestones,
and output generation. Use `DEBUG` for page IDs, engine selection, eligible-region
and face counts, assignment modes, and matching outcomes. Recoverable skips and
failed requests use `WARNING` or `ERROR` as appropriate. Repeated initialization
reuses existing root handlers, including the worker's rotating file handler for
the same log filename. The worker retains its format, date-format, and file options.

Project loggers use module names and parameterized messages. Diagnostics omit
credentials, proposed person names, OCR/caption text, API response bodies, and
exception messages that may contain private payloads. Database and LLM failures
report the operation, HTTP status or exception type, and retry number where
applicable. JSON decoding failures still propagate to database callers after a
safe diagnostic. Worker logs report job IDs, subprocess exit status, and stdout/
stderr character counts; arbitrary child output is not copied into logs.

The worker retains the subprocess failure propagation introduced by
[PR #31](https://github.com/LIBCAS/PeopleGator/pull/31).

The entity-merging CLI reports its document page count and completion at `INFO`,
with at most ten page-count progress updates per document. Page identifiers and
individual merge details remain at `DEBUG`.

## Text entity detection (`TEXT_ENTITY_DETECTION`)

`LLMTextEntityDetectionEngine` receives and returns the same document, runs the
independent chunker once, and attaches unresolved mentions to page layouts. It
needs processing extras and the configured OpenAI-compatible Responses service;
it never loads images or requires GPU inference or PeopleGatorApp credentials.
Configure it in ordinary engine order, for example in an INI under `resources/`:

```ini
[ENGINE_1]
METHOD = TEXT_ENTITY_DETECTION
API_URL = https://example.invalid/v1
API_KEY = your-service-key
MODEL_NAME = your-model
PROMPT_TEMPLATE_PATH = ./prompts/text_entity_detection.json
REASONING_EFFORT = low
MAX_OUTPUT_TOKENS = 2000
CHUNKING_METHOD = LINES
CHUNKING_MAX_CHARS = 4000
CHUNKING_OVERLAP_CHARS = 400
MENTION_MATCH_SCORE_CUTOFF = 80
```

Shared LLM defaults are `REASONING_EFFORT=low`, `MAX_OUTPUT_TOKENS=1000` and
three request attempts. Only extracted, stripped `CHUNKING_*` options reach the
chunker factory; omitted options retain its defaults, and unknown chunking keys
raise an error. `MENTION_MATCH_SCORE_CUTOFF` must be finite and numeric in 0–100.

The detector has no built-in prompt or handwritten JSON schema. Supply
`PROMPT_TEMPLATE_PATH` using the shared `LLMBasedEngine` JSON format, with `system`
and/or `user` Jinja2 templates. Relative paths resolve from the INI directory.
`text` contains the current OCR chunk and is the only supplied template variable.
The [text detection template](../resources/prompts/text_entity_detection.json)
preserves the complete prompt previously documented here. Select it explicitly
with `PROMPT_TEMPLATE_PATH`, or supply your own populated file.

Prompt configuration validation is inherited from `LLMBasedEngine`, as for all
LLM engines. `LLMTextEntityDetectionEngine` has no prompt-loading override or
separate path checks. Missing/broken prompts fail during initialization before
prompter construction or OCR loading, with safe actionable errors. There is no
built-in fallback prompt. See the
[shared prompt contract](#shared-llm-prompt-configuration-and-data-diagnostics).

`TextEntityMentionResult`, `TextEntityResult` and `TextEntityDetectionResult` are
Pydantic models in `people_gator/engines/text_entity_detection.py`. The engine
passes the **class** `TextEntityDetectionResult` to `LLMPrompter(response_model=...)`,
which derives the Responses API JSON schema using `model_json_schema()` and
returns a validated model instance. No separate `JSON_SCHEMA_PATH` is needed;
model-generated schemas take precedence over that inherited shared setting,
matching the existing face/entity engines.

The result contains an `entities` array. Each entity has canonical `name`,
literal `type=being`, nullable `info`, and a `mentions` array of verbatim
`name`/`context` pairs.

Models require strings without coercing numbers to text, nonblank names/evidence,
and the literal type `being`. Strings retain original Unicode and whitespace.
The provider contract requires nullable `info`; runtime validation also accepts
omitted `info` as `None`. Unsupported types and malformed entities/mentions are
filtered individually by model validators, retaining valid predictions and safe
rejection counts. Private counts are excluded from generated schemas and JSON.
Malformed envelopes fail validation and retry; empty arrays remain valid.
A legacy top-level array is normalized to the same model semantics. No
intermediate JSON files are needed.

Matching searches contiguous context first, then names inside that context. Exact
matches take precedence; repeated contexts are accepted only if they identify one
unique name occurrence. Otherwise the prediction is rejected. Normalized matching
casefolds Unicode, collapses whitespace and removes line-break hyphenation while
retaining original offsets. The final fuzzy fallback uses standard-library
`SequenceMatcher` similarity and the configured score cutoff. It accepts only one
winning word-boundary interval with no alternative within two score points.
Fuzzy evidence must be 5–512 normalized characters, windows must be 80–120% of
evidence length, and searches are bounded to 512 word starts and 32 ends per start.
Larger or ambiguous searches are rejected. Both context and name need supported
evidence; an unrelated context is never reconstructed from a guessed name.
This is intentionally more conservative than the development reference's final
name-only fallback. Evidence wholly lost across a non-overlapping chunk boundary
cannot be recovered; configure sufficient overlap for expected mentions.

Accepted `name` and `text` store actual OCR substrings, including Unicode,
hyphenation and synthetic inter-line newlines. `source_spans` is an ordered tuple
of the chunker's immutable `SourceSpan` records, retaining page/region/line IDs,
original list indices and half-open transcription offsets. Synthetic separators
never receive OCR addresses. Single-line mentions also populate legacy `line`
and `span`; multiline mentions use `None` for both. `page_identity` is optional,
and `identity_name` safely returns `None` for unresolved mentions. Canonical name
and supporting description are stored separately as `proposed_name` and
`description`, ready for subsequent clustering. Addresses remain valid only while
the original OCR/layout ordering is unchanged.

Occurrences deduplicate by the complete source-span tuple, independent of chunk
ID. Distinct positions remain distinct. The first candidate in document/chunk/
response order wins conflicting metadata deterministically; existing annotations
always win, including legacy manual single-line annotations matched by line object
and offsets. Repeated runs append no duplicates and never rewrite manual metadata.
The engine creates no document clusters or database IDs.

Empty source and whitespace-only chunks trigger no request. Valid empty arrays
produce no mentions. Malformed entities, unsupported types and invalid/unmatched
mentions are skipped individually with safe rejection counts. Transport, JSON and
invalid-envelope responses retry through `LLMPrompter`; unrecoverable failures raise
`RuntimeError` naming numeric page/chunk positions. New annotations are staged until
all chunks succeed, so failure leaves the document unchanged. Logs contain counts,
positions and failure types, never OCR, names, response payloads or credentials.

Text-mention ALTO/PAGE serialization and app persistence remain follow-up work
in #33; clustering and face cooperation are described below; XML export does not persist this engine's
in-memory text detections.

### Standalone text-detection inspection CLI

With `.[tool]` or `.[full]` installed, inspect OCR detections independently of the
other stages configured in an existing INI file:

```bash
# Read ALTO pages and print mentions with their source locations.
python -m user_scripts.detect_text_entities \
  --config ./config.ini --input-alto-path ./input/alto

# Read PAGE pages and write a structured diagnostic snapshot.
python -m user_scripts.detect_text_entities \
  --config ./config.ini --input-xml-path ./input/page \
  --output-path ./output/entities.json
```

`--config` and exactly one input option are required. The utility finds exactly
one `[ENGINE_*]` section whose `METHOD` is `TEXT_ENTITY_DETECTION`; zero or multiple
matches are errors. It calls the normal factory for that section only, with CPU
as the device and resource paths relative to the configuration file's directory.
Other engine sections, `[DB_API]` and `[PARSE_FOLDER]` are not executed. No images,
GPU inference, database credentials or DocAPI installation are needed.

The directory must contain readable, valid XML pages in the selected format.
Pages load as one `PeopleGatorDocument`, retaining the existing loader's page
order. JSON and stdout results group mentions by original source page, ordered by
the document's `page_layouts` list. **Every input page is represented**, including
pages with zero detections. Page IDs can be absent or repeated: the zero-based
`page_index` disambiguates them. Each page's mentions and each mention's source
spans retain their existing order and original OCR provenance. Repeated runs
with the same page order and model results produce the same JSON.

Without `--output-path`, stdout prints the total mention count, then a header
for each page (ID, index and per-page count), followed by its mentions and
region/line IDs, indices and half-open offsets. If **no** page has any mentions,
stdout also prints `No text entity mentions detected.` and retains the zero-count
page headers. For a document with no input pages, only that message is printed.

With `--output-path`, missing parent directories are created and the complete
UTF-8 JSON file is written via a temporary sibling and atomic replacement.
Nothing is printed to stdout in this mode. Errors/diagnostic logs go to stderr.
Configuration, XML loading, detection and output-writing errors return a nonzero
exit status. Failed detection creates no output; a failed write preserves an
existing result and removes its temporary file. Provider/parser exception payloads
are omitted from error messages. An existing output file from a previous successful
run remains intact on failure; the exit status identifies whether this run succeeded.

The diagnostic JSON contract is **page-grouped**.

The top-level `document_id` is nullable (the XML-only loader supplies no
document metadata); `pages` is an array of objects with `page_id`,
`page_index`, and `mentions`. A document with no pages has `"pages": []`;
a page with no detections has `"mentions": []`. Duplicate or missing page
IDs are legal, so identify a source page by its `page_index` as well as its
ID. The former flat, top-level `mentions` field is no longer emitted.

Within each page, `name` and `context` are exact source evidence;
`proposed_name` and `description` are nullable detection metadata. Each
ordered `source_spans` element retains original page/region/line IDs (which
may be missing/repeated), original zero-based list indices, and half-open
`start`/`end` offsets in the OCR line transcription. Synthetic newlines
have no span. Span-level page fields remain for complete standalone provenance
even though mentions are grouped under their source page. Layout objects,
chunk IDs, prompts, credentials and app identities are excluded. This is an
inspection interface, not ALTO/PAGE annotation export, database persistence or
document clustering.

The diagnostic CLI accepts `--logging-level DEBUG|INFO|WARNING|ERROR` (default
`INFO`), matching the main processing CLI. For example, append
`--logging-level DEBUG` to inspect initialization and engine diagnostics, or use
`--logging-level ERROR` to show only failures. Logging is initialized before
loading configuration; diagnostics use the module logger and stderr, and repeated
initialization reuses existing handlers. Mention listings remain stdout data and
JSON files retain the same schema at every logging level. Logs report counts and
failure types without printing OCR, names, credentials or provider payloads.

The diagnostic utility also supports direct script execution, including from a
different working directory:

```bash
python -u /path/to/PeopleGator/user_scripts/detect_text_entities.py \
  --config=/path/to/config.ini --input-alto-path=/path/to/alto --logging-level=DEBUG
```

This form explicitly uses the PeopleGator sources alongside the script, preventing
an older installed package from masking the checkout's detector implementation.
Runtime dependencies must still be available in the selected Python environment.
An unavailable detector is reported during configuration, before XML loading.

### Incomplete LLM output and JSON decoding failures

`MAX_OUTPUT_TOKENS` limits the complete model output, including reasoning tokens.
A reasoning model can exhaust a small allowance before finishing its JSON. The
Responses API identifies this as `status=incomplete` with reason
`max_output_tokens`; any returned text may be empty or truncated JSON. Repeating
the same request with the same allowance does not resolve that condition.

The shared prompter reads and parses output only when the response explicitly
has `status=completed`. Failed, cancelled, queued, in-progress, unknown and
missing/null statuses are request failures, even if the response includes
plausible JSON. Such responses are retried within the configured attempt limit;
exhaustion raises `LLMRequestError` with `raise_on_failure=True` or returns `None`
in the default mode. They discard any earlier unvalidated payload and cannot
trigger clustering's content-only singleton fallback. Clustering therefore leaves
the original cluster list intact if any candidate request fails.

The shared prompter rejects incomplete responses before JSON decoding,
reports the configured cap, recommends increasing `MAX_OUTPUT_TOKENS`, and
stops identical retries. The configured limit
remains a hard limit; the client never silently raises it. For the configured
reasoning model tested with roughly 3,600 synthetic source characters, 1,500
output tokens truncated the result while 6,000 allowed complete JSON. Choose a
budget appropriate for the model, reasoning effort and expected mention count.

At `DEBUG`, response diagnostics include only text length and output/reasoning
token counts. Genuine JSON decoding errors identify whether decoding failed in
the SDK's HTTP response handling or in the model's output, plus the character
position. These project diagnostics exclude response bodies, OCR, prompts and credentials.

## Document text entity clustering (`TEXT_ENTITY_CLUSTERING`)

`LLMTextEntityClusteringEngine` receives and returns the same document, populating
`text_entity_clusters` in memory. Place its `[ENGINE_*]` section **after
`TEXT_ENTITY_DETECTION` and before face detection, face assignment and identity
linking**. Section insertion order controls execution, not the section suffix.
It reads existing mentions across all pages without chunking, images, GPU, app
access or intermediate files. Detection and clustering remain separate stages.

| Option | Required | Default | Meaning |
| --- | --- | --- | --- |
| `METHOD` | Yes | — | `TEXT_ENTITY_CLUSTERING` |
| `API_URL`, `API_KEY`, `MODEL_NAME` | Yes | — | Existing shared LLM connection settings, supplied externally. |
| `PROMPT_TEMPLATE_PATH` | Yes | — | External JSON containing system/user Jinja2 templates; shared validation applies. |
| `REASONING_EFFORT`, `MAX_OUTPUT_TOKENS` | No | Shared `LLMBasedEngine` settings | Existing request controls; size the token allowance for candidate groups. |
| `CLUSTER_THRESHOLD` | No | `92` | Finite candidate score in `0–100`, inclusive. |
| `NAME_WEIGHT` | No | `0.7` | Finite nonnegative canonical-name weight. |
| `MENTION_WEIGHT` | No | `0.3` | Finite nonnegative OCR-alias weight; weights must have a finite positive sum. |
| `SIMILARITY_AGGREGATION` | No | `max` | `max`, `mean` or `min` across weighted name/alias comparisons. |

The [clustering placeholder](../resources/prompts/text_entity_clustering.json)
contains only `{}` because no complete prompt was previously documented.
**Fill it with valid system/user templates before enabling this engine**, or
configure another populated external file. No provider/model choice is supplied. A
`JSON_SCHEMA_PATH` is unnecessary: the nested Pydantic v2 response model always
supplies the generated request schema. The existing shared template validation
and missing/unused key warnings apply to this engine too.

Each **mention is one record**, because extraction does not retain a separate
NER entity grouping. The canonical name is `proposed_name` when nonblank,
otherwise OCR `name`; its alias is the original OCR `name`. The reference fuzzy
algorithm compares every canonical/alias pair using RapidFuzz
`partial_token_sort_ratio` on NFKC/casefold/word-normalized comparison copies.
The original evidence stays untouched. A pair score is multiplied by the sum of
its two weights divided by twice the largest weight. `max`/`mean`/`min`
aggregates the four scores. Threshold graph connected components are equivalent
to reference DBSCAN with `min_samples=1`, including threshold `100` (exact
candidate similarity); no distance matrix or extra scikit-learn dependency is
needed. Comparisons take quadratic time and the grouping uses linear storage.
Initials, reordered/omitted parts and OCR variants can become candidates.
Alternative names can meet through existing canonical proposals. Unrelated
aliases without that evidence remain separate. Context does not establish a
fuzzy edge: it is supplied for LLM disambiguation, including conflicting
homonyms. Similarity alone never merges records.

A singleton copies its original proposed/OCR name and description without an LLM
call. For each multi-record group, the engine sends one Jinja2 data key:
`entities`, a UTF-8 JSON string of ordered records with `index` (one-based,
restarted for each request), `name`, `aliases`, `description`, and OCR `context`.
These local indices refer directly to original mention objects; they are not
page/chunk IDs. Templates may render `{{ entities }}` or decode/format it using
external template logic. The external prompt must ask for evidence-based
resolution, permit homonym splits and uncertainty, choose a supplied name, and
avoid facts outside the supplied evidence. Code contains no disambiguation
wording.

`TextEntityClusteringResult` has `clusters: list[TextEntityClusterResult]`. Each
nested result has `name: str`, nullable `short_description` and
`long_description`, and `entity_indices: list[int]`. All fields are required in
the generated structured-output schema; use JSON `null` for absent descriptions.
Extra fields and coercion (including string/float/bool indices) are rejected.
Every request index must occur exactly once across nonempty groups. The chosen
name must match a canonical name or OCR alias **of its own members** under the
comparison normalization. Text must be nonblank and contain no control/surrogate
characters except normal newline, carriage return or tab. Descriptions are LLM
summaries of supplied evidence; structural validation cannot prove the factual
accuracy of an arbitrary summary, so external prompts and human review remain
responsible for that judgment.

Unusable decoded content, unsupported names, or invalid membership rejects the
**whole candidate partition**, logs a warning with counts, and preserves each
record as a singleton using original metadata. The shared prompter owns JSON
parsing and retries. Clustering enables the shared prompter’s opt-in
`raise_on_failure` mode: exhausted invalid model JSON/schema raises
`LLMResponseError` and uses singleton fallback; request/HTTP decoding, transport
and all non-completed responses raise `LLMRequestError` and abort after request
handling/retries. An earlier invalid payload cannot mask a subsequent request
failure. Existing prompter callers
retain their default return behavior. A raised request error or `None` from
a request aborts processing with a safe error. All groups are staged before replacing the cluster
list; no partial clustering is committed on failure. Diagnostics report only
counts/failure types, never names, OCR, prompts or credentials.

Existing clusters are protected as complete units, retaining their objects,
membership, names, descriptions and identities. An unclustered mention with any
`page_identity` is also protected, becoming a singleton with that existing
identity (even when its app ID is null). Only unclustered mentions without page
identity enter candidate grouping. Conflicting non-null app IDs within an
existing cluster, empty/overlapping/foreign membership or a mention object reused
in input raise `ValueError` before processing, leaving annotations intact rather
than guessing how to repair them. Distinct objects with equal OCR or reused
page/line IDs remain distinct records. Reruns preserve prior clusters and process
only new mentions; they do not reopen earlier singleton or LLM decisions. To
intentionally recluster, callers must explicitly remove the relevant unlinked
clusters first. Existing app-ID-based helper behavior is unchanged.

Every source mention appears exactly once. New members retain input order and
clusters sort by their earliest document/page/mention position; existing member
order is preserved. `PeopleGatorTextEntityCluster.identity` now defaults to
`None`, while old positional constructor usage still works. `name` is the
consolidated proposal, `description` stores the long description (or short when
long is null), and the new optional `short_description` preserves the concise
version. Original OCR spellings, line/span, ordered `source_spans`, extraction
metadata and `page_identity` are never rewritten or distributed. No fabricated
app ID or provisional database identity is created. Aliases remain available
through the original members.

This output is an in-memory handoff for face cooperation (described below) and
shared identity linking (described below). No new ALTO/PAGE text serialization, database
persistence, face assignment or detection occurs here.

## Text evidence in face assignment

Configure `TEXT_ENTITY_DETECTION` → `TEXT_ENTITY_CLUSTERING` →
`FACE_DETECTION_YOLO` → `LLM_FACE_ASSIGNMENT` or `LLM_BATCH_FACE_ASSIGNMENT`
in INI section insertion order. Both assignment engines read the original
in-memory document; they do not rerun detection/clustering or call the app.
Earlier text stages are optional. The existing face images, marker colors,
face ordering, relative coordinates, result models and identity persistence
remain the same. Batch result mapping requires the complete supplied coordinate
pair, rejecting partial coordinates rather than matching their prefix. Single-face requests consume the shared prompter's structured
`FaceAssignmentResult` or `None` directly. In both engines, a missing response
or a null, empty or whitespace-only `name_normalized` leaves the existing name,
identity object and app/authority IDs unchanged. Only strings with non-whitespace
content are applied; their original spelling and whitespace are retained.
The external response models and generated JSON schemas remain unchanged, and
no manual/verified-state fields are introduced.
A page without OCR uses zero context margins.

Both engines use the same image-relative selection policy, also in sequential,
page-parallel and document-parallel batch execution:

| Jinja input | Contents and evidential weight |
| --- | --- |
| `caption_entities` | Detected mentions associated with this image's assigned caption; preferred direct textual context. |
| `surrounding_entities` | Original mention lines intersecting the image's existing context crop; strongest fallback locality. |
| `page_entities` | All mentions on the image's page, including outside the crop; weaker page context. Local mentions deliberately also occur here, labeled `page`. |
| `document_entities` | Off-page-only provisional clusters, or unclustered off-page mentions; weakest background context. |

These inputs are JSON-compatible **lists**, not JSON strings. Render them with
Jinja's `tojson` filter (or iterate their records). All four keys are supplied so
external templates have predictable empty values. If caption entities exist,
the other three lists are empty and the prompt must render only the caption
entity section. Otherwise render all three fallback sections, **even when
empty**. Available `caption_text` and `context_text` remain supplied in either
branch. With no detected mentions all lists are empty and the existing image/
OCR/caption behavior remains usable. A direct `process_page`/`prepare_face_data`
call without the optional `document` argument can use page evidence only;
`process_document(document)` supplies cross-page context in every mode. With a
document, original page positions are authoritative. Without one, a page's
original index is inferred only when its valid mapped mentions agree on one
nonnegative source index. Later pages retain that index in both record and span
provenance; they are not renumbered to zero. Legacy mentions on the same page
inherit a known index from those mappings. A legacy-only standalone page has an
unknown index, serialized as `null`, while original line/character references
remain usable. Conflicting standalone mapped indices remain page evidence with
unknown index and no claimed source spans; pass the original document to resolve
that ambiguity. This concerns face-request records only; stored `SourceSpan`
objects and the chunker/detection diagnostic contracts are unchanged.

Caption text retains the existing `graphical_metadata.title` convention, with
Czech, then English, then the first language value preferred for dictionaries.
When AnnoPage supplies `caption_lines_metadata`, only references to original OCR
**line objects** with nonblank transcription are usable. Reconstruct a mapped
caption view from **only those lines**, in the existing OCR reading order, joined
by synthetic newlines. Unrelated intervening article lines are excluded, and
reference-list order or duplicate references cannot reorder or duplicate source
text. Region/line indices and original character offsets remain unchanged.
Locate the assigned title uniquely in that reconstructed view using the same
whitespace/dehyphenation comparison and character mappings. Every mention span
must lie completely inside that title occurrence, including legacy and multiline
mentions across nonadjacent original lines. Two captions
sharing one OCR line therefore receive only their own names; line membership
alone does not establish caption association. Valid references can disambiguate
a title repeated elsewhere on the page. If the assigned title is absent,
paraphrased or repeated within those usable lines, use the surrounding/page/
document fallback rather than attributing the whole line to the caption.

Missing, empty, foreign, stale or untranscribed caption-line references are
unavailable. A reused XML ID never makes a foreign line usable. In these cases,
first locate the assigned title uniquely in the entire page OCR. Every mention
span must lie inside that exact title occurrence, including when the same name
occurs elsewhere on the same line. A repeated title remains ambiguous and cannot
establish caption association. Only if the title cannot be located in OCR, the
**entire original mention context** (`mention.text`) may establish a match within
the assigned title, with Unicode word boundaries. Comparison
copies collapse whitespace and remove line-break hyphenation (`-` or soft hyphen
followed by a newline); case, spelling, punctuation and stored evidence remain
unchanged. Canonical/proposed names, fuzzy matches and substring names never
establish caption association. Identical context and source name at distinct
page occurrences are ambiguous and excluded from this text-only association.
This conservative rule may fall back when a title paraphrases or contains only
part of a longer detected context; it does not invent a caption source location.

Surrounding evidence resolves `SourceSpan` page/region/line **indices** against
the unchanged original document, validates character offsets, and tests positive
area intersection of any original mention line with the context crop. It does
not estimate character boxes. The existing OCR `context_text` retains its 50%
line-overlap rule; a partly intersecting mention line can therefore be supplied
as a surrounding entity even when absent from `context_text`. Multiline mentions
retain all their spans. Legacy `line`/`span` mentions resolve by line object
membership and offsets. Unavailable/invalid mappings cannot establish spatial
locality or override a located caption; the mention remains page evidence. Repeated XML IDs do not affect
selection.

Each mention record contains `provenance` (`caption`, `surrounding`, `page`,
`document`), container `page_index`/`page_id` (`page_index` is nullable for
standalone pages whose original index cannot be determined), verbatim `name` and `context`,
nullable `proposed_name` and `description`, and ordered `source_spans` with the
original IDs, indices and half-open offsets. Optional `cluster` contains `name`,
`short_description`, `description`, and `provisional: true`. Cluster lookup uses
**mention object membership**, never name equality or app IDs.

Off-page clusters are represented once, in document/page/mention order, with
`provenance: document`, `provisional: true`, `name`, `short_description`,
`description`, unique original `aliases`, and `sources` containing off-page
mention records. The whole cluster is excluded if **any** member occurs on the
current page. Equal cluster names do not merge distinct clusters. Unclustered
off-page mentions stay separate, including homonyms; repeated references to the
same mention object are omitted within a section. Original evidence, source
ordering and identities are not changed. No database identifiers are exposed
as candidate identities and no face-to-cluster link is created.

### External face prompt contracts

The [single-face placeholder](../resources/prompts/llm_face_assignment.json) and
[batch placeholder](../resources/prompts/llm_batch_face_assignment.json) contain
only `{}`. The earlier guide supplied a migration fragment rather than complete
identification/normalization prompts. **Provide complete system/user templates
before enabling either engine**, or configure your own populated files.

Both templates receive `caption_text`, `context_text`, `caption_entities`,
`surrounding_entities`, `page_entities`, and `document_entities`. The single-face
engine also supplies `face_coordinates` (the face center as integer percentages
of the context image) and two images: the face crop then marked context. The batch
engine supplies `faces` (ordered ID, coordinate pair and color descriptors) and a
marked context image. Render structured values with `tojson` or iterate records.
Keep all four entity inputs in each template: render only caption entities when
present, otherwise the three fallback sections, including empty collections.

Prompt instructions must distinguish the evidence strengths described above,
decide faces independently using positive visual/caption evidence, and retain
null names on uncertainty. Provisional clusters, proximity, frequency or a sole
off-page candidate do not establish correspondence. Treat OCR/entity content as
data, preserve supplied face IDs/coordinates, and retain your corpus-specific
name-extraction and normalization rules. Templates are never rewritten at runtime;
shared warnings identify missing or unused inputs.

The unchanged `FaceAssignmentResult` has nullable `name_in_text` and
`name_normalized`; `BatchFaceAssignmentResult` contains a `faces` array adding
the supplied `id` and `coordinates` to those names. Generated Pydantic schemas
need no separate JSON schema file or additional LLM request. Model judgment
requires corpus review. Shared app linking follows in `ENTITY_MATCHING`; text
XML serialization remains step 7 of #33.


## Document-wide entity linking (`ENTITY_MATCHING`)

This existing engine now handles prebuilt `text_entity_clusters` once per document
(including singletons) and already named faces, using the same shared `[DB_API]`
connection and required external `PROMPT_TEMPLATE_PATH`. No new engine key, extra,
or service is introduced. Configure section order as:

```text
TEXT_ENTITY_DETECTION → TEXT_ENTITY_CLUSTERING → face detection/LLM naming (optional) → ENTITY_MATCHING
```

Text-only, face-only, mixed and empty documents are supported. The optional future
DB-based assignment of still-unnamed faces (step 5 of #33) is independent and is
not required. Unnamed/unusable face proposals cause no search or mutation. Without
`[DB_API]`, linking logs a warning and returns the document unchanged. Cluster
membership must be nonempty, disjoint and refer to original document mentions;
invalid membership fails before any app request.

### Evidence, retrieval and conservative decisions

Stable cluster order precedes independent faces in page/region order. Explicitly
shared `PeopleGatorIdentity` objects resolve together. A named face can also join
one unique relevant caption cluster when the existing `FaceEntityContext` selector
confirms original caption character spans and the face's exact normalized name
matches a supplied cluster name/alias. This uses source membership, never a search
score, fuzzy name similarity or same-page occurrence. Missing/ambiguous caption
associations leave units separate. Conflicting non-null app IDs prevent contextual
reconciliation; explicit groups containing conflicts remain unchanged.

Queries contain distinct canonical names, observed/proposed aliases and supplied
descriptions. `DatabaseApiService.search_entities(query)` still accepts one string
and now also accepts a sequence, sent as repeated `query.text` values. Every
unique retrieval ID is hydrated with `get_entity_info`; malformed hits/details,
HTTP/JSON failures and `None` are errors, not empty results. Candidate scores and
untrusted indices are excluded from decision data. Earlier resolved/created
same-name records are also offered as candidates during this run, covering index
lag; they are not automatically selected. Separate homonymous clusters stay
separate, even when both ultimately resolve to the same app ID.

All decisions use the shared prompter with `raise_on_failure=True` and the strict
Pydantic class `EntityMatchingResult`. Names, aliases, descriptions and source
contexts are supplied to the **LLM for semantic assessment**. The external prompt
instructs it to select a supported existing person, create only when the evidence
justifies a distinct person (or a reliable named source has no candidates), and
return `unresolved` on insufficient evidence. A retrieval score or vague hit alone
is not identity proof; a single hit still goes through the LLM.

The **engine validates structure and references only**: a supported action, a
nonblank reason, a named person source for selection/creation, a real zero-based
candidate index, the selected candidate's exact name and `entity_type=person`,
and the original proposed name for creation. It does not compare free-form
descriptions or quoted fragments to determine sameness or difference. The `reason`
is retained on the typed decision without interpreting or logging its contents.
Malformed/failed decisions raise safely; explicit `unresolved` outcomes leave
annotations unchanged and never fall through to creation.

Equivalent duplicate app records do not require a unique choice: the LLM can
select a matching existing record. Deduplicating, merging or rewriting those
records belongs to the human/application data-quality workflow in PeopleGatorApp.
This engine performs none of those operations.

Creation supplies source names, distinct aliases and original cluster descriptions
(member descriptions provide a fallback). It generates no biography and never
patches existing app records. The app contract remains `entity_type=person`;
fictional/mythological person-like beings use that same existing category, with
no new subtype/ontology support. Organizations and other non-person sources
must not link or create through this engine.

### External linking prompt contract

The existing Jinja inputs remain `name`, `context`, `entities`. **`context` is now
a mapping**, containing `name`, `aliases`, `short_description`, `description`,
`descriptions`, `captions`, and ordered `sources`. Each source contains exact OCR
name/context, detection/cluster proposals, page provenance and source spans.
`entities` contains hydrated app records with trusted zero-based `item_id`,
`entity_id`, `entity_type`, `name`, aliases and descriptions. Render mappings with
`tojson` rather than assuming `context` is a caption string.

The [entity matching template](../resources/prompts/entity_matching.json)
preserves the complete prompt previously documented here. Configure it explicitly
or supply another populated file requesting the typed decision. The response has
five required fields: `action`, `source_is_person`, `item_id`, `name`, and `reason`.
Legacy responses containing only an item index/name, or the earlier quotation-based
`evidence` field, fail strict validation. Quote extraction, description equality
and text normalization are not part of decision validation. A selection copies
the trusted candidate index and exact name; creation uses a null index and the
source name; unresolved uses null index/name. Every decision needs a nonblank
reason explaining the assessment.

No separate schema file is needed; generated Pydantic schemas take precedence
over inherited `JSON_SCHEMA_PATH`. Strict validation rejects extra keys, booleans
as integer indices, unsupported actions, invented indices/names, missing fields
and contradictory action fields. `MAX_OUTPUT_TOKENS` and other shared settings
retain their existing meaning.

### Propagation, protected links and retry limits

Every non-null existing app ID is protected, irrespective of origin; the model
has no reliable manual/verified state, so linking conservatively protects all of
them. Conflicting IDs are never merged or reset. A single protected ID can fill
missing IDs in its explicit unit without another API operation. Original identity
objects, names, authority IDs, face/page provenance, OCR spellings, source spans,
line offsets and cluster membership remain intact. New wrappers share the cluster
identity; existing wrappers/identities retain their own local metadata and receive
the same app ID. No database-ID regrouping is performed.

`distribute_text_entity_identities(clusters=None)` now distributes resolved IDs
only, skips conflicting/unresolved clusters, preserves existing identity objects
and allocates unique nonblank `person_text_*` / `MODS_PERSON_TEXT_*` IDs when a
mention needs a wrapper. The optional subset argument supports focused propagation;
XML export uses the same safe helper. Full text annotation XML/API persistence
and round-trip remain **step 7 of #33**; these changes provide its in-memory handoff.

Successful units apply immediately. A later read/model/write failure raises a safe
`RuntimeError` identifying the numeric unit; prior successful IDs remain available
for retry. Logs identify the operation and exception type without credentials,
OCR, names, model bodies or private explanations. Reruns skip protected resolutions.

`PeopleGatorDocument.entity_linking_journal` is an **in-memory** list of creation
receipts (`state`, original object `targets`, source evidence, `entity_id`). A receipt
is marked `uncertain` before POST; malformed/missing responses or exceptions retain
that state and no app ID is fabricated. Retries of the same document skip uncertain
targets and matching names/aliases with an actionable warning until a caller
reconciles the app state. A successful response records `created` and its ID before
propagation, so interrupted propagation can replay the receipt. Face-only direct
`process_page` calls retain equivalent receipts on their page object.

There is no server idempotency key or durable run journal in this contract.
Receipts do not survive reconstruction/restart or step-7 serialization; concurrent
processes can race. After an uncertain write, reconcile the remote app before
rebuilding/retrying the document or intentionally clearing its receipt. Never
assume search-index absence proves that a timed-out create did not succeed.
