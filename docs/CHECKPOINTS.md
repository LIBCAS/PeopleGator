# Processing checkpoints and recovery

Checkpointing is optional. Set a directory in the existing processing section:

```ini
[PARSE_FOLDER]
PROCESSING_CHECKPOINTS = ./processing-checkpoints
```

Or pass `--processing-checkpoints DIR` (also `--processing-checkpoints=DIR`).
The CLI value overrides the INI, including an explicit empty string to disable
snapshots. If both are absent or empty, processing creates no checkpoint files
or recovery ledger. This is neither an engine nor a separate INI section.
Checkpoint and other `[PARSE_FOLDER]` document paths resolve from the process
working directory. Engine resource paths still resolve from the INI directory.

```bash
peoplegator --config config.ini --input-alto-path input/alto \
  --input-image-path input/images --processing-checkpoints processing-checkpoints \
  --output-alto-path output/alto

peoplegator --config config.ini \
  --resume-from-checkpoint processing-checkpoints/DOCUMENT/RUN/ATTEMPT/0002-ENGINE_TEXT_CLUSTERING.checkpoint.json \
  --processing-checkpoints processing-checkpoints --output-alto-path recovered/alto
```

Replace the illustrative IDs with an actual finalized snapshot. Supply a complete
current configuration and credentials again. Resume never loads the document
from XML or imports app annotations again: it reconstructs the saved intermediate
object graph, skips the completed prefix and executes the first unfinished engine.
It then runs requested app and XML/render outputs. A final-engine snapshot can
be used for local output retries without running any engine. The original import
setting must remain the same for compatibility; the import itself is skipped.

## Files and JSON contract

Each new run gets random document/run identifiers, even for missing/repeated
source document IDs. Snapshots are placed under
`DIRECTORY/DOCUMENT_UUID/RUN_UUID/ATTEMPT_UUID/ORDINAL-SECTION.checkpoint.json`.
Each resume has a fresh attempt identifier; it appends snapshots to the same
history without modifying earlier ones. `parent_checkpoint` links the selected
snapshot and subsequent stages. `latest.json` in the original run directory is
an advisory pointer, never a resume file. A failed write may leave this pointer
behind the newest snapshot; inspect finalized files when recovering.

Schema version **1** has these top-level fields:

| Field | Meaning |
| --- | --- |
| `schema_version`, `created_at` | Version and UTC creation timestamp. No migration of other versions is attempted. |
| `document_id`, `run_id`, `attempt_id` | Opaque storage/history identifiers. |
| `document_identity` | Original logical document ID and library, also verified against the graph. |
| `run_directory`, `parent_checkpoint` | Location of the required original durable ledger and processing-history parent. |
| `initial_configuration`, `initial_options` | Sanitized effective initial INI sections in insertion order, after CLI path/flag overrides; effective app flags include direct parser options. |
| `execution_configuration` | Sanitized settings for the current execution, retaining the initial baseline separately. |
| `pipeline` | Ordered zero-based ordinal, exact engine section, `METHOD`, and sanitized per-section configuration hash. Repeated methods remain separate stages. |
| `completed_steps` | Exact successful prefix, with stage identity, completed status, finish timestamp and engine duration. |
| `last_completed`, `next_step` | Last completed ordinal and first unfinished ordinal (pipeline length means finished). |
| `model_identity` | SHA-256 of the audited model implementations, including inherited classes and event handlers. |
| `input_assets` | Original XML set, metadata and page-image references with sizes and SHA-256 integrity checks. |
| `document` | JSON object table with `root`, `objects` and `{ "ref": index }` references. |
| `integrity_sha256` | Canonical JSON checksum of the other fields, detecting corruption, not proving authenticity. |

Each successful engine result is saved before the next engine. No snapshot is
created for a throwing engine, including its partially modified in-memory state.
All attributes of supported model objects are traversed, including extra metadata;
unknown populated types, missing audited fields, unsupported handlers and array
types fail closed instead of producing an incomplete checkpoint. Mutable cycles
and original object aliases are preserved. Types and dict/list/tuple ordering are
retained. Small numeric arrays expose readable values, dtype and shape; larger
arrays, crops and in-memory images use compressed base64 data inside JSON. No
pickle, arbitrary imports, constructors from checkpoint data, partial `to_dict()`
methods or lossy XML writers are used to reconstruct the document.

External page images stay lazy when they were lazy. Cached images, including
modified pixels that differ from their JPEG, are saved in the object table and
restored unchanged. Original XML is checked as an external dependency because
existing ALTO enrichment uses it as the output base; it is **never** substituted
for the saved layout. Original metadata JSON is retained as `source_metadata`,
including keys not interpreted by the existing loader.

## Audited inherited state

The audit uses the packaging pins: pero-ocr `204a989b51b97256704fcf098878b99d1e958a3c`
and AnnoPage `1fa885d55d516f782ed5ac2fcabe8801e5fb8838`. The serializer checks the
inherited constructor fields explicitly and serializes **all** additional fields.
The tests populate these structures on real ALTO and PAGE fixtures and compare
every attribute, type, order and original reference, rather than only counts.

| Model | Audited state |
| --- | --- |
| pero `PageLayout` | ID, size, regions, reading order (including object keys), confidence, embeddings, metadata, all 14 XML event objects and their ordered handlers. |
| pero `RegionLayout` | ID, polygon, type/category, lines, transcription, detection confidence, embeddings, metadata. |
| pero `TextLine` | ID/index, baseline/polygon/heights, transcription, dense or CSC/CSR/COO sparse logits and their full attributes, crop, characters, logit coordinates, character/transcription confidence, category, embeddings, metadata. |
| AnnoPage page/region | Inherited pero fields and all graphical metadata; inherited and PeopleGator XML handlers retain their exact order and functions. |
| AnnoPage `BaseMetadata` | Tag/MODS IDs, UUID, record identifier, model provenance, creation date/time, confidence. |
| AnnoPage `GraphicalObjectMetadata` | Tag description, multilingual caption/topics/color/description/title, continuing line, prompts, caption and reference metadata. |
| AnnoPage `RelatedLinesMetadata` | Inherited provenance, original line references, relation enum, description and multilingual title. |
| AnnoPage color/enums | Color mode, dominant color names/coverage, typed Language/Category/LineRelation values, including enum dictionary keys. |
| PeopleGator | Complete document/page state, all metadata, face/source-region references and landmarks, page/person identities and authority IDs, original mentions/legacy line links and offsets, SourceLine/SourceSpan records, document clusters, shared identities and journal receipt targets. |

Standard metadata values also support dates/times with fixed-offset timezones,
UUIDs, native-platform paths, bytes, bytearrays,
sets/frozensets, NumPy scalars and nonfinite numbers using tagged representations.
Arrays with object/structured dtypes or extra dtype metadata, overlapping distinct
array views, custom timezones/subclasses, arbitrary callables and unsupported foreign
objects require an explicit adapter; checkpoint creation fails with a safe error.
This prevents silent loss of data or view relationships. Ordinary independently
owned crops and shared references to the same array are supported. Checkpoints
are application data, not an arbitrary Python object persistence interface.

## Compatibility and relocation

Resume validates the schema/checksum, complete graph, logical document identity,
model implementations, ordered pipeline and completed prefix, initial non-secret
settings, resource content and external inputs before running any engine.
Malformed files, temporary files, pointer files, changed resources, absent inputs
and inconsistent histories produce an error; processing never falls back to
starting over or silently accepting changed completed work.

The current INI must supply the entire original pipeline in its original order,
with identical settings. This strict rule applies to unfinished stages too.
Engine prompt/schema/model `*_PATH` resources are identified by their entire
file content hash and size; a path may move if the file bytes remain identical.
Missing resources fail validation. Endpoint/model names, generation limits
(including `MAX_OUTPUT_TOKENS`) and other inference settings must match. Model
code fingerprints must match, so changing the inherited model implementation
requires using the original software to recover this schema version.

Credentials (`API_KEY`, password/passwd, token, secret, credential, authorization,
and private-key options) are replaced with presence/required markers; no secret
or secret hash is persisted. Current credentials may rotate, but required
credentials cannot be removed. Usernames and service endpoints are non-secret
compatibility settings. Credential-bearing URLs and credentials embedded in
other settings/document metadata are rejected. Place authentication in dedicated
credential options. ConfigParser interpolation is resolved before sanitizing.

The processing device selection is recorded in `initial_options` and must match
on resume. Current `[PARSE_FOLDER]` input paths may relocate the same files; file contents,
XML filenames/set and page-image content must match. Missing replacement paths
use original saved paths. Output directories and checkpoint destinations can
change. App export/drop flags may change independently of engine work; this
allows local-only output recovery. The original app import flag must match.
Do not change a source file in place or use an output directory as an input
directory: integrity checks will prevent further recovery from that history.

The **original run directory and its ledger must remain accessible**, even if
resumed snapshots go elsewhere or are disabled with `--processing-checkpoints ''`.
Moving input resources is supported; relocating or losing the durable history
ledger is not an automatic recovery operation. Preserve the complete history
until processing and any app reconciliation are finished.

## Crash recovery and external side effects

Snapshot publication uses a private temporary sibling, full JSON serialization,
file flush/fsync, atomic rename and a directory fsync on POSIX. Earlier snapshots
survive a failed write. Temporary files (including complete but unfinalized ones)
are not resume points. Snapshot completion is recorded in memory only after
publication and the latest pointer succeed. A process lock prevents concurrent
resumes of the same history and is released by the OS after a crash.

App mutations cannot be made transactional by saving JSON. The version-1 recovery
policy fences the **entire `ENTITY_MATCHING` stage** in a durable `run-state.json`
**before** executing it. If that stage may have run after the selected snapshot,
replay is blocked, even if a later search index does not yet show the new person.
Choose its completed post-engine snapshot when one exists: that graph includes
successful identity IDs and original linking receipts. Otherwise reconcile with
PeopleGatorApp manually before starting a new run. The client cannot establish
whether an interrupted create succeeded, so it never blindly repeats that stage.
The fence is deliberately conservative even for read-only/unresolved matching
attempts; there is no server idempotency key or automatic rollback guarantee.
Other completed engines are never rerun on resume. A crash inside a pure engine
can recover only its preceding fully completed snapshot.

The run ledger is checksummed too; missing, malformed or damaged ledgers cannot
authorize replay. Every app export attempt is durably fenced before document/page/face/image/layout
writes. A repeated export in the same history is blocked whether the earlier
attempt succeeded, failed or crashed, including `DROP_EXISTING_ANNOTATIONS`.
Reconcile partial app data manually; do not delete/reset the ledger to retry.
A local-only resume remains available with app export disabled in the current
INI. If needed, create a separate reviewed operation after reconciliation.
Existing export functions can log failed individual operations rather than
raising, so even a normal return is treated as an attempted export, never as
proof that all records were stored. Engine checkpoints precede all final exports;
XML/render output retries do not imply app retry permission.

Checkpointing-disabled fresh runs retain the existing app behavior. Starting a
new independent run does not consult previous run ledgers; operators must not
use a fresh run to evade an unresolved app operation. No automatic worker retry,
server checkpoint storage or exactly-once protocol is introduced.

## Privacy, retention and validation

Snapshots include private OCR, names, prompts recorded as document annotations,
and original metadata. Store them outside version control in access-controlled
storage with an appropriate retention/backup policy. New run/attempt directories
are private (`0700`) and JSON/ledger files use `0600` on POSIX. Existing parent
folder permissions remain the operator's responsibility; filesystem ACLs apply
on Windows. Routine checkpoint diagnostics omit document payloads, paths and
credentials. Do not publish a snapshot as a log or attach it unredacted to an issue.

The conventional `processing-checkpoints/` directory and `*.checkpoint.json`
files are ignored by Git; add any custom checkpoint directory to local ignore
rules too, because its ledger/pointer also contains private references. Retain
all required source assets and the original run ledger together. After review,
reconciliation and the retention period, remove only the selected run's history,
its resumed attempt directories and abandoned temporary siblings. Never clean
an active history. Loss of the ledger intentionally prevents unsafe replay.

Run deterministic tests without a live LLM, database or GPU:

```bash
python -m pytest -q tests/test_checkpoints.py tests/test_entity_matching.py tests/test_documentation.py
```

They cover full inherited graph equivalence, every engine boundary, repeated
methods, disabled mode, CLI precedence, modified cached/lazy images, input and
resource relocation/integrity, interrupted publication, failed engines, secret
redaction, durable create/export fencing and restored real linking receipts.
