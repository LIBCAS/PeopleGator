# Processing prompt resources

Select these files explicitly through each engine's `PROMPT_TEMPLATE_PATH` in
the INI passed to `python -m user_scripts.parse_folder --config ...`.
[config.example.ini](config.example.ini) shows all engine sections in processing
order, with paths relative to the INI directory. Operators can use other populated
files, including absolute paths outside the repository, without changing code.

| Engine | JSON file | Status / supplied Jinja inputs |
| --- | --- | --- |
| `TEXT_ENTITY_DETECTION` | [text_entity_detection.json](prompts/text_entity_detection.json) | Complete prompt moved unchanged from the guide; `text` is the OCR chunk. |
| `TEXT_ENTITY_CLUSTERING` | [text_entity_clustering.json](prompts/text_entity_clustering.json) | Uploaded clustering prompt; `entities` is a JSON string of request-local mention records. |
| `LLM_FACE_ASSIGNMENT` | [llm_face_assignment.json](prompts/llm_face_assignment.json) | Uploaded single-face prompt; uses `face_coordinates`, caption/OCR text and face/context images. The four optional entity lists are not referenced. |
| `LLM_BATCH_FACE_ASSIGNMENT` | [llm_batch_face_assignment.json](prompts/llm_batch_face_assignment.json) | Uploaded batch-face prompt; uses `faces`, caption/OCR text and marked context image. The four optional entity lists are not referenced. |
| `ENTITY_MATCHING` | [entity_matching.json](prompts/entity_matching.json) | Complete prompt moved unchanged from the guide; `name`, structured `context`, and hydrated `entities`. |

Text detection and entity matching preserve the complete prompts previously in
`docs/PROCESSING.md`; clustering and both face prompts now contain user-supplied
JSON copied without modifying their content. All five files are populated and
use generated Pydantic response schemas. The current face prompts do **not**
render `caption_entities`, `surrounding_entities`, `page_entities` or
`document_entities`; the shared prompter warns about these unused inputs and
cannot include detected text-entity evidence in those LLM requests. Update the
external face prompt JSON explicitly to incorporate that evidence if desired.
No bundled default or resource discovery exists. Assess prompt quality against
your corpus.

See [Processing](../docs/PROCESSING.md#shared-llm-prompt-configuration-and-data-diagnostics)
for validation and each engine's variable/response contract. Deploy the INI and
referenced files together, preserving relative paths or using accessible absolute
paths. For workers, provision them relative to the worker engine's `config.ini`.
These repository resources are not automatically installed as wheel package data.
Credentials, service endpoints and face models must be supplied separately.
