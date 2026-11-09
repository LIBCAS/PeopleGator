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

`ENTITY_MATCHING` uses the connection described in [Database API](#database-api).

The LLM settings come from `LLMBasedEngine` in `people_gator/engines/llm.py`. Run detection before face assignment, and face assignment before entity matching when using all three stages.

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

## DocAPI worker

Install `.[worker,tool]` or `.[full]` to run processing jobs. For example:

```bash
peoplegator_worker --api-url https://docapi.example.org --api-key YOUR_WORKER_KEY \
  --device gpu --gpu-id 0 --logging-level INFO
```

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
Configure it in ordinary engine order, for example:

```ini
[ENGINE_1]
METHOD = TEXT_ENTITY_DETECTION
API_URL = https://example.invalid/v1
API_KEY = your-service-key
MODEL_NAME = your-model
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

The deterministic `DEFAULT_PROMPT` and `DEFAULT_SCHEMA` live in
`people_gator/engines/text_entity_detection.py`. They request real, fictional,
mythological and other person-like beings only, using the boundary label
`being`. The Responses schema is object-wrapped:

```json
{"entities": [{"name": "canonical proposed name", "type": "being",
  "info": "source-language description or null",
  "mentions": [{"name": "verbatim OCR name", "context": "contiguous OCR context"}]}]}
```

`PROMPT_TEMPLATE_PATH` overrides system/user Jinja2 templates via the existing
JSON file format. Both `text` and `chunk_text` contain the current OCR chunk.
`JSON_SCHEMA_PATH` overrides the provider generation schema. The detector always
validates the envelope and individual candidates against its extraction contract,
independently of provider enforcement. A legacy top-level array is normalized to
the same semantics. No intermediate JSON files are needed.

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

Text-mention ALTO/PAGE serialization, app persistence, clustering and face
cooperation remain follow-up work in #33; XML export does not persist this engine's
in-memory text detections.
