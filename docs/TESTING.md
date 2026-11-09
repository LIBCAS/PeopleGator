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
Configuration tests extract and strip `CHUNKING_*` keys from a sample future
NER `[ENGINE_1]` section while leaving its own `METHOD` and LLM settings intact.
They cover `LINES`/`LINE_AWARE`, defaults, partial options, lowercase ConfigParser
keys, unknown extracted options and rejection of whole-engine/prefixed config.
These are lightweight adapter examples; no NER engine is introduced.
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
