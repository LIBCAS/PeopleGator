# Processing prompt resources

Select these files explicitly through each engine's `PROMPT_TEMPLATE_PATH` in
the INI passed to `python -m user_scripts.parse_folder --config ...`.
[config.example.ini](config.example.ini) shows all engine sections in processing
order, with paths relative to the INI directory. Operators can use other populated
files, including absolute paths outside the repository, without changing code.

| Engine | JSON file | Status / supplied Jinja inputs |
| --- | --- | --- |
| `TEXT_ENTITY_DETECTION` | [text_entity_detection.json](prompts/text_entity_detection.json) | Complete prompt moved unchanged from the guide; `text` is the OCR chunk. |
| `TEXT_ENTITY_CLUSTERING` | [text_entity_clustering.json](prompts/text_entity_clustering.json) | **Empty `{}` placeholder**; `entities` is a JSON string of request-local mention records. |
| `LLM_FACE_ASSIGNMENT` | [llm_face_assignment.json](prompts/llm_face_assignment.json) | **Empty `{}` placeholder**; `face_coordinates`, caption/OCR text and four entity lists, plus face/context images. |
| `LLM_BATCH_FACE_ASSIGNMENT` | [llm_batch_face_assignment.json](prompts/llm_batch_face_assignment.json) | **Empty `{}` placeholder**; `faces`, caption/OCR text and four entity lists, plus the marked context image. |
| `ENTITY_MATCHING` | [entity_matching.json](prompts/entity_matching.json) | Complete prompt moved unchanged from the guide; `name`, structured `context`, and hydrated `entities`. |

Only complete prompts previously documented in `docs/PROCESSING.md` are populated.
Clustering had no prompt and face assignment had only an incomplete migration
fragment. **Fill those `{}` files with complete system/user templates, replace their
configured paths, or remove the engine sections before running.** Shared runtime
validation rejects empty templates; no bundled default or discovery exists.
The two populated examples are structurally usable; assess model/corpus quality
for your deployment. All five engines supply generated Pydantic response schemas.

See [Processing](../docs/PROCESSING.md#shared-llm-prompt-configuration-and-data-diagnostics)
for validation and each engine's variable/response contract. Deploy the INI and
referenced files together, preserving relative paths or using accessible absolute
paths. For workers, provision them relative to the worker engine's `config.ini`.
These repository resources are not automatically installed as wheel package data.
Credentials, service endpoints and face models must be supplied separately.
