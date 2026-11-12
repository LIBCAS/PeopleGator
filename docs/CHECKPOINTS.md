# Processing checkpoints and recovery

Enable checkpoints in the existing `[PARSE_FOLDER]` section with
`PROCESSING_CHECKPOINTS = ./processing-checkpoints`, or pass
`--processing-checkpoints DIR`. The CLI overrides the INI, including an empty
string to disable snapshots. If both are absent/empty, no checkpoints or ledger
are created. Document/checkpoint paths resolve from the process working directory;
engine resource paths resolve from the INI directory. No new section/engine exists.

```bash
peoplegator --config config.ini --input-alto-path input/alto \
  --input-image-path input/images --processing-checkpoints processing-checkpoints \
  --output-alto-path output/alto

peoplegator --config config.ini \
  --resume-from-checkpoint processing-checkpoints/DOCUMENT/RUN/ATTEMPT/0002-ENGINE_TEXT_CLUSTERING \
  --output-alto-path recovered/alto
```

Use the actual stage directory, or its `checkpoint.json`. Resume requires the
complete current config and credentials again, skips completed engines and the
initial app import, and performs the requested final exports. The original import
flag must match even though import is skipped. The final-engine checkpoint allows
local output retries without executing engines. Keep original inputs and the
original run ledger accessible, even if resumed checkpoint output is disabled
with `--processing-checkpoints ''` or redirected elsewhere.

## Hybrid format and publication

Each stage is a separate directory:
`DIRECTORY/DOCUMENT_UUID/RUN_UUID/ATTEMPT_UUID/ORDINAL-SECTION/`.
It contains **`document.pkl`** (authoritative complete Python document) and
**`checkpoint.json`** (small, readable metadata and commit marker). New runs use
new UUIDs; each resume uses a new attempt directory and appends snapshots without
overwriting originals. `parent_checkpoint` connects the selected history;
`latest.json` in the original run directory is an advisory pointer, not a resume file.

The JSON schema is **version 2**. Earlier JSON-only snapshots are unsupported;
there is no migration or long-term archival/portable interchange guarantee.

| Metadata | Contents |
| --- | --- |
| Identity/history | Schema version, UTC timestamp, document/run/attempt UUIDs, logical document ID/library, original ledger directory and parent checkpoint. |
| Configuration | Sanitized initial INI sections in original insertion order after CLI overrides, initial app/device options, and separately sanitized current execution settings. |
| Pipeline/completion | Exact section name, ordinal, METHOD and per-section identity; successful ordered prefix with finish/duration/status, last completed and next stage. |
| Compatibility | Python implementation and exact major/minor/micro version, Pickle protocol **5**, PeopleGator/pero-ocr/AnnoPage/NumPy/SciPy/OpenCV/lxml versions, and hashes of layout, metadata, source-mapping and callback implementations. |
| Integrity | Payload filename `document.pkl`, byte size and SHA-256; original XML/image/metadata paths and content hashes; metadata checksum. |
| Summary | Counts of pages, text regions/lines, non-text regions, faces, mentions, clusters and distinct resolved app identities. This is diagnostic, not document state. |

The native Pickle memo preserves object identity, cycles and shared references.
No object table, bespoke JSON type codecs, class registry or partial `to_dict()`
reconstruction is used. Every populated attribute is checked against the local
unpickled result before publication, including extra/inherited metadata, reference
aliases and array data. A non-pickleable callback/runtime object, lossy custom
`__getstate__`, changed type/field or lost array-view relationship fails creation
instead of silently dropping state. Live authenticated clients/sessions are rejected;
only recoverable document state belongs in a checkpoint.

Unchanged decoded page-image cache entries reference their integrity-checked JPEG
instead of duplicating pixels. Modified cached images remain in the Pickle.
Lazy images stay lazy. Cached aliases are retained. Missing/altered inputs fail
recovery. Original XML is checked because the existing ALTO output path uses it as
an output base; it is never re-imported to replace saved intermediate annotations.
`source_metadata` retains the complete original metadata JSON, including unused keys.

Publication creates a private stage, writes/flushes/fsyncs and atomically finalizes
`document.pkl`, registers the locally produced manifest checksum in the durable
run ledger, then writes/flushes/fsyncs and atomically publishes **`checkpoint.json`
last**. POSIX directory entries are synced. A directory without the marker, a
missing/mismatched payload, or temporary files cannot resume. Earlier valid stages
survive payload/manifest failures. Failed engines never publish completion. The
latest pointer can lag after a failed advisory update; finalized pairs remain valid.

## Inherited-model audit

Tests load real ALTO and PAGE fixtures using packaging pins pero-ocr
`204a989b51b97256704fcf098878b99d1e958a3c` and AnnoPage
`1fa885d55d516f782ed5ac2fcabe8801e5fb8838`, populate inherited state and compare every
field/type/value/order/reference after Pickle round-trip. Native Pickle handles
the current callbacks, so no state-dropping `__getstate__` hooks are needed.

| Model | Verified state |
| --- | --- |
| pero PageLayout | ID/size, ordered regions/reading order including object keys, confidence, embeddings, metadata and all 14 XML events with ordered inherited/native handlers. |
| pero RegionLayout/TextLine | Complete geometry, baselines/heights, IDs/index/order, transcription, type/category, detection and character/transcription confidences, dense/CSC/CSR/COO logits and their full attributes, crops, characters/logit coordinates, embeddings and metadata. |
| AnnoPage | Non-text regions/detections, complete BaseMetadata provenance, multilingual captions/titles/topics/descriptions/colors, color coverage, continuing line, caption/reference metadata and links to original OCR lines, enums and prompt annotations. |
| PeopleGator | All document/page metadata, faces/landmarks/source-region links, person/page identities and authority IDs, original mentions/legacy line links/offsets/SourceSpans, cross-page clusters/shared identities and linking-receipt targets. |

Standard Python/NumPy metadata now uses native Pickle support, including
structured arrays, dtype metadata and importable timezone/callback objects.
Distinct overlapping NumPy views that native Pickle cannot preserve faithfully
are rejected; detach those views before checkpointing. Unpickleable local/lambda
callbacks and unknown lossy state require targeted restoration support, not omission.

## Trusted loading and compatibility

**Pickle can execute code. Never resume or inspect an untrusted/downloaded/shared
checkpoint, even if its SHA-256 matches. Checksums detect corruption; they do not
authenticate a malicious manifest, ledger or payload.** Only locally generated
checkpoints in protected storage are accepted. The loader requires the original
private run ledger, its registered marker path/checksum, private owned stage/run
files and directories on POSIX, and no symlinked files. Arbitrarily copied or
externally supplied pairs are rejected. These provenance/permission checks do
not protect against a malicious actor already able to modify your private history
or Python environment; treat both as trusted code. Windows uses filesystem ACLs.

Before unpickling, both resume and inspection validate JSON schema/completion
history, UUIDs and ledger registration, Python/Pickle/package/code compatibility,
required external inputs, payload size/hash and actual protocol header. Resume
also validates the complete ordered current pipeline, resources and initial
settings before unpickling. No failure silently restarts/skips stages. The
payload is read once, and the verified bytes are the bytes passed to the unpickler.

The current config must retain all engine sections/order/settings, endpoints,
usernames, device selection and initial import flag. This strict rule covers
unfinished stages too. Prompt/schema/model resource paths may relocate identical
bytes; input paths may relocate identical images/XML/metadata (same XML set).
Output/checkpoint destinations and final export/drop choices can change.
Credentials (`API_KEY`, password/passwd, token, secret, credential, authorization,
private-key options) become required/presence markers without secret hashes.
Credentials may rotate, but required ones must be supplied again. Credential-bearing
URLs, embedded copies and credentials in document state/Pickle bytes are rejected.

## Read-only JSON inspection

```bash
python -m user_scripts.inspect_checkpoint /protected/stage-directory
python -m user_scripts.inspect_checkpoint /protected/stage/checkpoint.json \
  --details ocr entities --output-path /protected/diagnostics/stage-2.json
```

This applies the same trust/environment/input/payload checks before loading.
It does not initialize engines or app clients, execute import/export, or write to
checkpoint history. It emits selected OCR transcription/geometry/confidence,
region categories/polygons/source links, mentions/source offsets and cluster member
indices/resolved IDs, alongside counts and document identity. `--details` selects
`ocr`, `regions`, and/or `entities`; stdout is the default. Explicit output files
are private and cannot overwrite registered checkpoint history. Compare these
exports between stages to understand changes. This selected diagnostic JSON is
intentionally not a second lossless recovery representation. Inspection needs no
LLM/DB credentials or inference configuration; resource fingerprints are available
in metadata and no inference is performed.

## App recovery, privacy and retention

A checksummed durable ledger fences the entire `ENTITY_MATCHING` stage **before**
it runs. If a stage may have written after the selected snapshot, replay is
blocked even when search-index absence suggests no result. Use its completed
post-stage checkpoint if present: it contains IDs and original creation receipts.
Otherwise reconcile manually with PeopleGatorApp before a new run. Uncertain
receipts also stop recovery. No server idempotency, rollback or exactly-once
claim is made. A run lock prevents concurrent resumes and is released on crash.

Every app export attempt is fenced before writing records/images/layouts,
including successful, partially failed and destructive replacement exports.
Repeats in the same history require manual reconciliation. Existing export
functions can log individual failures without raising; a return is never proof
that all writes succeeded. Local-only output retry remains possible with app
export disabled. Engine checkpoints precede final app/XML/render exports.
Independent new histories do not reconcile old app operations; never start one
to bypass an unresolved write. Worker retry/storage protocols are outside scope.

JSON diagnostics and Pickle can contain private OCR, names, prompts and metadata.
New directories use `0700`; marker/payload/ledger files use `0600` on POSIX.
Keep trusted histories outside version control, with access-controlled backup and
appropriate retention. Ignore rules cover `checkpoint.json`, `document.pkl` and
the conventional `processing-checkpoints/`; custom directories need local ignore
rules for ledgers/pointers too. Routine errors/logs omit private content and paths.
Retain original assets and ledgers until processing/reconciliation finishes, then
remove only the selected inactive history, redirected stages and abandoned staging
files under your retention policy. Never publish unredacted diagnostic exports.
