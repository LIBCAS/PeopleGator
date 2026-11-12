# Processing prompt resources

Select these files explicitly through each engine's `PROMPT_TEMPLATE_PATH` in
the INI passed to `python -m user_scripts.parse_folder --config ...`.
[config.example.ini](config.example.ini) shows all engine sections in processing
order, with paths relative to the INI directory. Operators can use other populated
files, including absolute paths outside the repository, without changing code.

| Engine | JSON file |
| --- | --- |
| `TEXT_ENTITY_DETECTION` | [text_entity_detection.json](prompts/text_entity_detection.json) |
| `TEXT_ENTITY_CLUSTERING` | [text_entity_clustering.json](prompts/text_entity_clustering.json) |
| `LLM_FACE_ASSIGNMENT` | [face_assignment.json](prompts/face_assignment.json) |
| `LLM_BATCH_FACE_ASSIGNMENT` | [batch_face_assignment.json](prompts/batch_face_assignment.json) |
| `ENTITY_MATCHING` | [entity_matching.json](prompts/entity_matching.json) |

All five templates are audited against the current engine inputs, generated
Pydantic response schemas and downstream validation. They treat source strings
as untrusted evidence and preserve these contracts:

- Detection receives only `text` (an OCR-chunk string, no images). It requests
  person-like `being` entities with canonical proposals, verbatim mention
  names/contiguous contexts and nullable `info`: a source-grounded identifying
  description, not a language code. No mentions means an empty `entities` array.
- Clustering receives only `entities`, an already serialized JSON string of
  one-based indexed name/alias/description/context records, without images.
  It requests a complete partition with observed names and nullable descriptions
  grounded only in input descriptions. Ambiguous homonyms stay separate.
- Both face prompts render `caption_text`, `context_text` and the four entity
  inputs. Nonempty `caption_entities` selects only that highest-priority,
  caption-associated entity section. Otherwise `surrounding_entities`,
  `page_entities` and off-page-only `document_entities` appear separately,
  including empty lists, in decreasing evidential strength. Records are safely
  serialized with `tojson`; optional text valued `None` renders as JSON null. Provisional
  candidates and overlapping page/local lists do not prove a specific face's
  identity. Ambiguity requires both names to be null.
- Single-face assignment receives `face_coordinates` and two appended images
  (face crop, then green-marked context). Batch assignment receives `faces`
  descriptors and one marked context image. Batch faces follow horizontal
  centers with stable ties; output preserves every request-local ID, coordinate
  pair and input order. Existing extraction/normalization rules remain in force.
- Matching receives `name`, a source-evidence mapping `context`, and hydrated
  candidate records `entities`, without images. Typed select/create/unresolved
  decisions use request-local `item_id`, never app `entity_id`. Descriptions are
  semantic LLM evidence, not Python quotation/equality requirements; equivalent
  duplicate app records remain eligible for selection without merging.

All supplied keys are referenced by the compiled templates, including conditional
face branches, so representative engine contexts render without missing/unused
key warnings. Prompts do not enforce model behavior: Python retains its existing
structural, source-mapping and reference checks. Assess identification, extraction
and summary quality against your corpus. No bundled default or resource discovery
exists.

See [Processing](../docs/PROCESSING.md#shared-llm-prompt-configuration-and-data-diagnostics)
for validation and each engine's variable/response contract. Deploy the INI and
referenced files together, preserving relative paths or using accessible absolute
paths. For workers, provision them relative to the worker engine's `config.ini`.
These repository resources are not automatically installed as wheel package data.
Credentials, service endpoints and face models must be supplied separately.
