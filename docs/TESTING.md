# Testing

Tests focus on PeopleGator's document-processing pipeline: loading pages, running processing engines, matching identities, and saving annotations. For a feature or bug fix, derive test cases from the issue's acceptance criteria and reproduce the reported bug before fixing it when practical.

## What should be tested

| Area | Important cases |
| --- | --- |
| Document loading | Page images, ALTO/PAGE layouts, metadata, and engine configuration/order |
| Face detection | Source-region filtering, bounding boxes, five landmarks, zero or multiple faces |
| LLM face assignment | Names proposed from image/OCR/caption context, single and batch results, missing responses |
| Entity matching | One, multiple or no person candidates; ambiguous and unassigned faces |
| ALTO XML | Face blocks, person and face tags, MODS references, coordinates, and existing OCR content |
| PAGE XML | Face regions, polygon coordinates, identity metadata, and source-region references |

Use synthetic documents and mocked model outputs or person-database responses so tests remain fast and repeatable. Include XML round-trip tests as the import functionality is implemented.

## How to run tests

Install the test/build tools from a checkout, then run the focused packaging tests or the full available suite:

```bash
python -m pip install -e '.[test]'
python -m pytest -q tests/test_packaging.py
python -m pip install -e '.[full,test]'
python -m pytest -q --runtime-mode=full
python -m build
```

`tests/test_packaging.py` validates dependency specifications and entry points, builds an sdist and a wheel from that sdist, checks every source module is packaged, and installs the wheel without dependencies into a temporary isolated environment to check lightweight imports and console-script registration. Build subprocesses use the already installed build tools without network access. This verifies distribution structure; it does not replace runtime dependency installation or processing checks.

`tests/test_runtime.py` checks installed engine and API imports outside the checkout, CLI help, API defaults with the DocAPI runner mocked, and synthetic PAGE-to-PAGE/ALTO processing with an empty engine configuration. The API starts a service rather than parsing `--help`. Runtime tests default to `--runtime-mode=full`, which requires both the processing stack and DocAPI: missing dependencies fail rather than silently skipping checks. For all runtime checks, install `.[full,test]` in a clean environment and run `python -m pytest -q --runtime-mode=full` and `python -m pip check`. Actual inference still requires a compatible model and configuration.

`tests/test_worker.py` mocks `subprocess.Popen` to check job input/metadata paths, every combination of ALTO/PAGE/render outputs, missing settings and optional values, mutually exclusive XML inputs, device/GPU selection, effective logging level, and worker CLI forwarding/defaults. It also checks that the original engine configuration is unchanged and no database/authentication arguments are passed. Run `python -m pytest -q tests/test_worker.py` with `.[worker,test]` or `.[full,test]`; these tests need DocAPI but no processing models, live service or GPU. Tool mode skips these DocAPI checks. The full runtime suite also runs a real worker subprocess on a synthetic PAGE document and checks ALTO, PAGE and rendered results.

`tests/test_worker.py` checks subprocess completion using mocked `Popen` results
and DocAPI's real `WorkerResponse`: success, positive and negative non-zero exit
codes, populated/empty stdout and stderr, missing job IDs, diagnostic logging,
failure-message contents, and unchanged subprocess arguments/environment. Run
`python -m pytest -q tests/test_worker.py` with `.[worker,test]` or `.[full,test]`;
no live service, processing model, or GPU is needed. Tool mode skips these DocAPI
checks.

Use a separate clean environment for each partial installation:

```bash
# Client-only environment: no AnnoPage, pero-ocr, PyTorch or Ultralytics.
python -m pip install '.[client,test]'
python -m pytest -q --runtime-mode=client
python -m pip check

# Local processing environment, without DocAPI.
python -m pip install '.[tool,test]'
python -m pytest -q --runtime-mode=tool
python -m pip check
```

The client mode asserts that the processing packages above are absent and exercises installed API/client imports, client help and the mocked API wrapper. Tool mode exercises processing imports, local command help and synthetic XML processing. Only checks outside the explicitly selected partial mode are skipped. `tests/test_packaging.py` runs with `.[test]` alone, including a dependency-free base wheel installation. Virtual-environment executable paths and console-script suffixes account for POSIX and Windows; execution on Windows and Python 3.10 still needs independent validation.

The wider processing regression suite and CI are still being established. For new processing tests, replace the focused module above with the tests added or modified. Confirm that the runner **collected and executed tests** and check its exit status.

For a syntax check of the processing code, run:

```bash
python -m compileall -q people_gator user_scripts
```

Syntax checks complement behavioral tests; they do not prove an issue is implemented. When dependencies or test tooling are unavailable, record the exact blocker and which acceptance criteria remain unverified. Keep the PR in draft while essential validation is incomplete.

## Text chunking

`tests/test_text_chunking.py` tests factory validation, public imports without
site packages, empty/irregular OCR, region reading order, page-local boundaries,
verbatim whitespace/Unicode, deterministic results and input preservation.
Configuration tests extract and strip `CHUNKING_*` keys from a sample
NER `[ENGINE_1]` section while leaving its own `METHOD` and LLM settings intact.
They cover `LINES`/`LINE_AWARE`, defaults, partial options, lowercase ConfigParser
keys, unknown extracted options and rejection of whole-engine/prefixed config.
These lightweight examples complement the registered detector tests below.
It enumerates budgets 1–12 and every valid overlap for several line patterns,
reconstructs canonical page text and checks every mapped source character,
exact overlap, progress and hard limits. Substring tests cover split lines,
multiline matches, synthetic separators and canonical overlap occurrence keys.
The ALTO/PAGE fixtures in `tests/resources/text_chunking/` load through the real
document model for one and two pages, including repeated IDs and PAGE reading
order. Only those XML integration cases require processing extras (and are
explicitly skipped in client mode); all other chunker tests use the standard
library plus pytest. Run:

```bash
python -m pytest -q tests/test_text_chunking.py tests/test_documentation.py
python -m pytest -q --runtime-mode=full
python -m compileall -q people_gator
```

## How to write new tests

1. Translate the issue's acceptance criteria into specific test cases. For a bug, add a regression case that exposes the old behavior when feasible.
2. Add `tests/test_*.py` files for the relevant processing components. Use small synthetic images, ALTO/PAGE XML and metadata fixtures in `tests/resources/`.
3. Mock face-detection models, LLM calls and person-database responses; use temporary output directories.
4. Check resulting face regions, identities and XML structure, including existing document content. Cover typical, empty and error cases.
5. Run focused and available full-suite checks. In the PR, map each acceptance criterion to the test or other evidence that verifies it, and report test outcomes and any remaining gaps.

See [Output formats](OUTPUT_FORMATS.md) for ALTO and PAGE XML examples.

## Logging and inline documentation

`tests/test_documentation.py` uses the Python AST to require docstrings for every
project-defined class and callable under `people_gator`, `processing_api`, and
`user_scripts`, including constructors, properties, and private helpers. It checks
Google-style parameter entries against signatures without importing optional
runtime dependencies. This establishes structural coverage only: semantic
accuracy, defaults, return values, and exception contracts still require manual
review against the implementation and its callers.

`tests/test_logging.py` uses captured records, synthetic pages, and mocked model,
HTTP, and subprocess responses to check logging levels, safe failure diagnostics,
empty inputs, handler reuse, and unchanged coordinates, identities, XML, and worker
results. It requires the applicable runtime extras; client/tool modes explicitly
skip tests belonging to the other runtime. Run both alongside the existing suite:

```bash
python -m pytest -q tests/test_documentation.py tests/test_logging.py
python -m pytest -q --runtime-mode=full
python -m compileall -q people_gator processing_api user_scripts
```

These tests make no live model/service requests. They check the current worker
success/failure contract from PR #31. Existing LLM response/validation behavior,
including known limitations, is preserved; passing tests do not establish that
those separate LLM defects are fixed.

## Text entity detection

`tests/test_text_entity_detection.py` uses mocked prompter/Responses results for
factory configuration, engine ordering, external prompt templates and generated model schemas,
malformed/empty/partial results, retries, failure atomicity, safe logs, occurrence
ambiguity, normalized/fuzzy OCR matching, Unicode and multiline spans, overlap
and rerun deduplication, legacy manual annotations and unresolved identity helpers.
Real ALTO/PAGE fixtures run through `DocumentParser` without images or app access,
retaining original OCR and pre-existing face annotations. These tests require
processing extras and skip explicitly in client mode. Run:

```bash
python -m pytest -q tests/test_text_entity_detection.py tests/test_text_chunking.py tests/test_documentation.py tests/test_logging.py
python -m pytest -q --runtime-mode=full
python -m pip check
python -m compileall -q people_gator
```

No live LLM, database or GPU inference is required. Passing mocked tests does not
establish extraction quality for a particular model or OCR corpus.

`tests/test_detect_text_entities_cli.py` exercises the standalone diagnostic
`main()` with real ALTO/PAGE fixtures and mocked LLM results, including Unicode,
multiline provenance, page-grouped stdout/JSON, repeated page IDs, stable page ordering, empty pages and documents,
exclusive detector selection despite face/linking/DB configuration, required
arguments and failures in configuration, XML, detection and writing. Atomic-write
regressions preserve an existing output and remove temporary files on failure.
Module subprocess checks cover help and a nonzero error exit. Run these with
processing extras (they skip explicitly in client mode):

```bash
python -m pytest -q tests/test_detect_text_entities_cli.py tests/test_text_entity_detection.py tests/test_documentation.py
```

The diagnostic CLI tests also cover the default `INFO` level, all supported
`--logging-level` values, invalid-level rejection, repeated logging setup without
duplicate handlers, captured error records, and unchanged stdout/JSON behavior.

Text-detector response-model tests verify nested Pydantic types, generated
provider schema and class-based prompter calls, typed response consumption,
strict candidate/evidence validation, partial-invalid filtering, private rejection
counts, unchanged Unicode/whitespace, legacy arrays, invalid envelopes and absence
of a built-in prompt/schema. The inherited JSON schema setting cannot override
the response model's generated schema.

The diagnostic CLI's direct-file regression runs its absolute script path from
outside the checkout, with a stale `people_gator` package on `PYTHONPATH`. It loads
empty synthetic OCR through the real engine without model requests and checks
successful JSON output. A separate regression requires an unavailable factory
engine to fail during configuration before any XML loading.

`tests/test_llm_responses.py` checks incomplete/token-limited Responses results,
including empty, truncated and superficially valid JSON. None is accepted as a
complete extraction or retried with an unchanged exhausted allowance. Tests also
check safe token-count diagnostics, HTTP-versus-model JSON decoding errors,
retention of the configured hard output limit and ordinary complete responses.
Non-completed status regressions cover failed/cancelled/queued/in-progress/unknown
and missing/null statuses with empty or apparently valid JSON, safe retries followed by a
completed response, opt-in request errors versus default `None`, and discarding
previous invalid content. Clustering regressions verify that a later failed
candidate group leaves the exact original cluster list and mentions unchanged,
without singleton fallback or a success log. Successful Responses mocks provide
an explicit `completed` status, matching the provider contract.
Run alongside detector, CLI, logging and documentation tests:

```bash
python -m pytest -q tests/test_llm_responses.py tests/test_text_entity_detection.py tests/test_detect_text_entities_cli.py tests/test_logging.py tests/test_documentation.py
```

Page-grouped diagnostic output regressions cover all-empty ALTO/PAGE documents
with every page retained in JSON and console headers, mixed empty/nonempty pages,
and repeated/missing page IDs disambiguated by original indices. They verify
Unicode/multiline evidence and ordered source spans survive the page grouping;
zero-page documents still produce an empty pages array and the no-mentions message.

`tests/test_llm_prompts.py` covers the updated shared prompt contract in
`LLMBasedEngine` for face assignment, batch face assignment, entity matching and
text detection. Missing/blank paths, unreadable/malformed/empty JSON, invalid
encoding, object/role types, blank content and Jinja2 syntax fail before prompter
or client construction. Valid system/user combinations use config-relative paths;
the text detector has no validation override. CLI failures load no OCR and leave
existing output unchanged.

Sequential and parallel prompter tests verify missing/unused key warnings, typo
handling, system/user union, shared variables, loop locals/globals, normal undefined
rendering, safe variable-name-only warnings and unchanged Pydantic response models
for every inheritor. The existing single/batch assignment request-flow regressions
now initialize real engines with explicit valid prompt files.

```bash
python -m pytest -q tests/test_llm_prompts.py tests/test_text_entity_detection.py tests/test_detect_text_entities_cli.py tests/test_llm_responses.py tests/test_logging.py tests/test_documentation.py
python -m pytest -q --runtime-mode=full
```

## Document text clustering

`tests/test_text_entity_clustering.py` tests weighted canonical/alias fuzzy
candidates, thresholds/weights/aggregation, OCR/Unicode/initial/reordered names,
contextual homonym splits, strict typed request-local partitions, missing/extra/
duplicate/noninteger/empty memberships, unsupported names, singleton fallback,
transport/exhaustion atomicity, deterministic ordering, reruns/new mentions,
protected manual/pre-linked clusters, conflicting IDs and invalid prior groups.
It verifies exact object/source-span preservation and image/face retention. Real
ALTO/PAGE fixtures pass through detection then clustering via `DocumentParser`,
with mocked Responses and no app, image loading or GPU inference. Shared prompt
tests include the new inheritor and generated Pydantic schema. Run:

```bash
python -m pytest -q tests/test_text_entity_clustering.py tests/test_text_entity_detection.py tests/test_llm_prompts.py tests/test_llm_responses.py tests/test_documentation.py
python -m pytest -q --runtime-mode=full
python -m build --no-isolation
python -m pip check
python -m compileall -q people_gator processing_api user_scripts
```

RapidFuzz is declared only in processing extras (`tool` and `full`); packaging
checks continue to exercise dependency-free base/client boundaries. Mocked
resolution tests do not establish model accuracy or factual summary quality on
real OCR. Python 3.10 syntax is checked independently of runtime availability.

## Face assignment with text evidence

`tests/test_face_assignment_text_entities.py` checks exact caption-only and
three-section fallback data; original caption-line association and conservative
text-only matching; Unicode, multiline/legacy spans and repeated IDs; local/page
overlap; page-only and off-page-only candidates; cluster membership, aliases,
whole-cluster on-page exclusion and unclustered homonyms. Real request preparation
in both assignment engines and all batch modes checks crops, face descriptors,
per-image correspondence, empty OCR/stages, null decisions and unchanged source
annotations. Review regressions cover preservation of previously named identities
and authority IDs on null normalized-name predictions in every execution mode,
with mixed named/null batch outcomes. Captions sharing one OCR line are separated
by exact character spans (including legacy mentions); missing, paraphrased or
ambiguous titles with usable references remain fallback evidence. Empty, foreign,
stale and untranscribed references try conservative title/evidence matching while
preserving repeated-title ambiguity. Direct page preparation and processing tests
cover later-page source indices with/without the document in both engines and
all batch modes, for caption and surrounding evidence, mixed legacy mappings,
unknown indices and conflicting standalone provenance. Noncontiguous caption
references are reconstructed in OCR reading order with original offsets, including
legacy/multiline names, shared lines, dehyphenation and repeated-title ambiguity.
The documented external JSON/Jinja migration
fragment is rendered through the shared prompter with populated and empty sections and unchanged
Pydantic provider schemas. No model, database or GPU inference is required.

```bash
python -m pytest -q tests/test_face_assignment_text_entities.py tests/test_llm_prompts.py tests/test_logging.py tests/test_documentation.py
python -m pytest -q --runtime-mode=full
python -m pip check
```
