# Testing

PeopleGator tests cover document loading, processing engines, identity linking, output formats, recovery and packaging. Treat the `tests/test_*.py` modules as the authoritative inventory of individual regressions; this guide explains their purpose and how to run them. Derive new cases from issue acceptance criteria and reproduce bugs before fixing them when practical.

## What should be tested

| Area | Required coverage |
| --- | --- |
| Document loading and processing | ALTO/PAGE input, metadata, engine selection/order, empty pages and errors |
| Face detection and assignment | Regions, coordinates, landmarks, image/OCR/caption evidence, single/batch modes and ambiguous results |
| Text processing | Reading order and OCR source spans, detection, clustering, identity propagation and unchanged original evidence |
| LLM and database integration | Prompt/schema validation, retries and failures, candidate decisions, protected IDs and partial app writes |
| Output and recovery | ALTO/PAGE round trips, linked text-mention export, diagnostic JSON, checkpoint pairs and stage-by-stage resume |
| Deployment | Dependency extras, installed entry points, worker subprocess outcomes, logging and documentation |

Use small synthetic documents and mocked LLM, model and database responses for deterministic tests. Verify **existing document content remains intact**, not only newly written fields. Mocked correctness does not establish model extraction or identity accuracy on a real corpus; live integration and corpus evaluation require separate tests.

## How to run tests

For the full processing/API environment, install the runtime and test dependencies and run:

```bash
python -m pip install -e '.[full,test]'
python -m pytest -q --runtime-mode=full
python -m pip check
python -m build
python -m compileall -q people_gator processing_api user_scripts
```

The full runtime mode requires both the processing stack and DocAPI: missing dependencies fail rather than silently skip tests. The build and syntax checks complement behavioral tests; neither proves the issue requirements on its own.

Use **separate clean environments** when testing partial installations:

| Environment | Install | Test command |
| --- | --- | --- |
| Client only (without processing stack) | `python -m pip install '.[client,test]'` | `python -m pytest -q --runtime-mode=client` |
| Local processing tool (without DocAPI) | `python -m pip install '.[tool,test]'` | `python -m pytest -q --runtime-mode=tool` |
| Packaging only | `python -m pip install -e '.[test]'` | `python -m pytest -q tests/test_packaging.py` |

Run `python -m pip check` in each environment. The partial runtime modes skip only tests requiring packages outside that mode; the client-only mode also checks that processing dependencies are absent.

`tests/test_packaging.py` checks dependency declarations and entry points, builds an sdist and wheel, and verifies packaged imports and commands without runtime dependencies. `tests/test_runtime.py` exercises installed imports, CLI behavior and synthetic PAGE-to-ALTO/PAGE processing (with DocAPI mocked where appropriate). `tests/test_worker.py` covers DocAPI job options, subprocess forwarding and success/failure propagation; run it with `.[worker,test]` or `.[full,test]`. The full suite also exercises a real worker subprocess on synthetic data.

Python 3.10 and Windows may require independent verification even when checks pass on another platform. Confirm that pytest actually **collected and executed tests**; record exact commands, outcomes and blockers in the PR. If essential validation is blocked, leave the PR in draft rather than claim success.

For changes confined to documentation, run applicable documentation checks and inspect links and contract references. Full processing tests are not necessary unless tested behavior changed.

## Text chunking

`tests/test_text_chunking.py` covers factory defaults/validation, `CHUNKING_*` option extraction, source reading order, verbatim Unicode/whitespace, line/page boundaries, hard budgets, overlap and synthetic separators. It verifies that every source character can be mapped back to its original page/region/line/offset, that overlapping windows have stable occurrence keys, and that source layouts remain unchanged. ALTO/PAGE integration fixtures require processing extras; lightweight chunk tests run without the processing stack.

```bash
python -m pytest -q tests/test_text_chunking.py
```

## How to write new tests

1. Convert agreed acceptance criteria into observable assertions; include typical, empty, realistic error and previously failing cases. Do not invent requirements or tests for speculative validation.
2. Prefer real domain models and supported interfaces (e.g. ConfigParser sections and the engine factory). Reuse small fixtures in `tests/resources/`; mock inference, LLM, app requests and other external services at their boundaries. Adapt unrealistic fixtures instead of adding production fallback or compatibility branches just to satisfy them.
3. Test observable behavior rather than private scaffolding. Direct helper tests are appropriate for meaningful algorithms such as OCR normalization and source-span resolution.
4. During refactoring, preserve regression coverage for exact outputs, original object relationships/provenance, processing/request order, mutation boundaries, failure handling and existing XML/document metadata as applicable. Use targeted traversal-count or reuse assertions when avoiding repeated work is an explicit requirement.
5. Remove or replace tests of superseded implementation details and requester-approved contract changes; distinguish approved changes from behavior preservation. Do not weaken meaningful coverage just to pass tests.
6. Keep tests focused and readable. Avoid duplicating equivalent fixtures or building helpers used only to hide straightforward setup. Run the affected modules and the applicable complete suite as described above, and report **actual** results and any unverified criteria.

See [Output formats](OUTPUT_FORMATS.md) for ALTO/PAGE examples and [Processing](PROCESSING.md) for engine contracts.

## Logging and inline documentation

`tests/test_documentation.py` checks class/callable docstring coverage and Google-style parameter names using the Python AST; structural presence does not establish semantic accuracy. `tests/test_logging.py` checks log levels, safe failure diagnostics, repeated setup/handlers, and unchanged output with mocked requests and jobs. They do not require live services.

```bash
python -m pytest -q tests/test_documentation.py tests/test_logging.py
```

## Text entity detection

| Test module | Main regressions |
| --- | --- |
| `test_text_entity_detection.py` | Engine configuration, strict/partial responses, exact/normalized/fuzzy evidence, Unicode/multiline source mapping, overlap/rerun deduplication, failure atomicity and ALTO/PAGE preservation |
| `test_detect_text_entities_cli.py` | Standalone ALTO/PAGE inspection, page-grouped stdout/JSON (including empty/repeated-ID pages), CLI/config errors, safe logging, atomic file replacement and direct execution outside the checkout |
| `test_llm_responses.py` | Completed/incomplete/failed Responses statuses, output-token limits, retries, malformed JSON, response privacy and request-error policies |
| `test_llm_prompts.py` | Required external prompts, valid JSON/Jinja roles, generated structured schemas, template-variable diagnostics and sequential/parallel requests |

```bash
python -m pytest -q tests/test_text_entity_detection.py tests/test_detect_text_entities_cli.py tests/test_llm_responses.py tests/test_llm_prompts.py
```

These tests use mocked Responses results. They verify source-grounded structure and controlled failure behavior, not the semantic quality of an LLM on unseen OCR.

## Document text clustering

`tests/test_text_entity_clustering.py` verifies name/alias fuzzy candidates, thresholds, contextual homonym separation and request-local complete partitions. It also checks strict response membership, singleton behavior, deterministic order, protected/pre-linked clusters, staged failure atomicity and preservation of original mentions/source spans. ALTO/PAGE integration uses mocked model output, with no app or GPU inference.

```bash
python -m pytest -q tests/test_text_entity_clustering.py tests/test_text_entity_detection.py
```

RapidFuzz is a processing-extra dependency; client/base installs remain free of it.

## Face assignment with text evidence

`tests/test_face_assignment_text_entities.py` covers sorting and request/result correspondence across single and batch modes; image crops and coordinates; caption-first evidence and surrounding/page/document fallbacks; Unicode, multiline/legacy provenance, homonyms and repeated IDs. Regressions ensure ambiguous or blank predictions do not erase protected identities, and that face/text association remains source-grounded. The historical face prompt fragment is retained as a test fixture, not a production prompt.

```bash
python -m pytest -q tests/test_face_assignment_text_entities.py
```

## Document-wide entity matching

`tests/test_entity_matching.py` covers text-only, face-only and mixed identities; hydrated app candidates; strict select/create/unresolved decisions; caption reconciliation; protected IDs, metadata and source preservation; retries and uncertain-creation receipts.

`tests/test_entity_matching_failures.py` covers recoverable per-unit app/LLM failures, safe diagnostic reasons, continuing later units, interruption propagation and final face prompt/output preservation. Explicit source descriptions remain **LLM evidence**, not deterministic Python equality checks.

```bash
python -m pytest -q tests/test_entity_matching.py tests/test_entity_matching_failures.py
```

Mocked decisions establish correctness of linking structure and error isolation, not identity accuracy or app database deduplication.

## Linked text-mention app export

`tests/test_text_mention_export.py` verifies one request per eligible occurrence, source IDs, exact OCR/name/context mapping, skipped invalid links, partial failures, face-only/text-only documents and preserved document state. Connector tests cover HTTP/response shape and errors; repeated export regressions preserve the known possibility of duplicates.

```bash
python -m pytest -q tests/test_text_mention_export.py
```

Live app compatibility, idempotency and import are not established by mocked tests. See [PeopleGatorApp text-mention export](OUTPUT_FORMATS.md#peoplegatorapp-text-mention-export).

## Configured prompt resources

`tests/test_prompt_resources.py` validates the five repository prompt JSON files and `resources/config.example.ini`, including Jinja inputs and schema compatibility. It exercises external prompt selection and relative/absolute paths without implicit resource discovery, plus representative detector, clustering, assignment and matching contexts.

```bash
python -m pytest -q tests/test_prompt_resources.py tests/test_llm_prompts.py
```

Prompt tests validate wiring, schemas and evidence boundaries, not factual quality of generated answers.

## Face prompt/response diagnostics

`tests/test_face_prompts.py` verifies independent per-face interaction lists, exact rendered role text and raw responses (including failures/retries), single/batch and multi-face matching association, ordered parallel results, and optional JSON export for every face. It covers collision-safe filenames, CLI/INI precedence, disabled/resumed output and native Pickle persistence without changing XML/app contracts.

```bash
python -m pytest -q tests/test_face_prompts.py tests/test_checkpoints.py
```

A real process-pool regression requires POSIX `fork`; other systems use deterministic inline-pool checks.

## Processing checkpoints

`tests/test_checkpoints.py` uses ALTO/PAGE fixtures to check native Pickle persistence of OCR, source references, identities, receipts and images. It exercises per-engine saves, ordinary read/write failures, CLI precedence, copied pairs, resumed exports and selected inspection output.

```bash
python -m pytest -q tests/test_checkpoints.py
```

Run with processing extras; tests mock LLM/app operations. The supported checkpoint format, trusted loading and recovery limitations are defined in [Processing checkpoints and recovery](CHECKPOINTS.md).
