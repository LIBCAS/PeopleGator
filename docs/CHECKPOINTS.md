# Processing checkpoints and recovery

**Only resume or inspect a checkpoint you trust. Loading a Python Pickle can execute code.** Keep the pair and any diagnostic exports in private storage. They can contain page images, OCR, names and raw LLM interactions.

## Save and resume

Set `PROCESSING_CHECKPOINTS = ./processing-checkpoints` in `[PARSE_FOLDER]` or pass `--processing-checkpoints DIR`. The CLI overrides the INI. An absent or empty setting disables saving, and relative checkpoint paths resolve from the working directory.

```bash
peoplegator --config config.ini --input-alto-path input/alto \
  --input-image-path input/images --processing-checkpoints processing-checkpoints
```

After each successful engine, the parser writes a new stage directory under `DIR/<run>/<stage-number>-<engine-class>/`. Numbering starts at 0001. Each invocation that saves gets its own run directory. Each stage contains two files, written in this order.

- `document.pkl` contains the complete document returned by the engine, including layouts, shared identities, prompts, linking receipts and any cached images.
- `checkpoint.json` contains the document ID, completed engine class, zero-based `last_completed` index and zero-based `next_step` index into the loaded engine list. Only `next_step` controls resume.

Pass the stage directory or its `checkpoint.json`. A copied pair works on its own. For example, if the first engine was face detection, substitute its actual run directory below.

```bash
peoplegator --config config.ini \
  --resume-from-checkpoint 'processing-checkpoints/<run>/0001-FaceDetectionYoloEngine' \
  --processing-checkpoints '' --output-alto-path recovered/alto
```

Resume skips fresh XML/metadata loading and the initial app import. It runs the remaining engines with the current settings, device and credentials. Choose a checkpoint whose index fits the intended engine order. To save subsequent stages elsewhere, supply a new checkpoint output directory. A final-stage checkpoint goes straight to the requested app and file exports, including relocated face-prompt output.

If an engine or save fails, use the last successfully written pair. An interrupted save can leave an incomplete stage. Filesystem, JSON and Pickle errors surface directly. Cached images can make the Pickle large. Keep original files at their recorded paths when a later operation needs them, such as lazy JPEG loading or ALTO export using the source XML.

## Inspect a stage

```bash
python -m user_scripts.inspect_checkpoint ./stage
python -m user_scripts.inspect_checkpoint ./stage/checkpoint.json \
  --details ocr entities --output-path diagnostics/stage.json
```

Inspection loads the same pair and prints JSON to stdout. With `--output-path`, it creates any missing parent directories and writes directly to the selected file. The two input files are protected from overwrite. It reports counts and document identity. Choose from `ocr`, `regions` (including faces) and `entities` (mentions, sources and cluster membership). Inspection requires the model classes and their dependencies only.

## App writes and legacy recovery

A checkpoint records state **after its engine and before final exports**. Resuming an older stage can repeat entity creation, append duplicate annotations or repeat a destructive app export. Check the app after an uncertain write, reconcile its state, and enable export only when intended. Receipts in the saved document reflect what the engine knew at that stage.

Native Pickle requires compatible Python classes and pickleable fields. The supported baseline is the new pair. Older payloads can contain custom external-image references or need legacy metadata handling. Keep the previous PeopleGator version and original history and assets for recovery of old checkpoints.
