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
