# Testing strategy

This describes the **planned test contract**, not a currently passing suite. At this draft's baseline, the `develop` branch has **no committed `tests/` suite, `pyproject.toml`, or CI test workflow**. Adding reproducible dependencies, fixtures, tests and CI requires follow-up implementation.

## Principles

- Ordinary pull-request checks must be deterministic, CPU-only and offline. Use synthetic page images, non-real person names, tiny ALTO/PAGE XML files and fake HTTP/LLM/model responses.
- Mock/inject YOLO inference, OpenAI-compatible Responses calls and PeopleGatorApp/DocAPI network access. Do not automatically download model weights, allocate GPUs, contact paid services or use shared/production databases.
- Test **observable document behavior and output structure**, including failures and boundary cases. Each test should pass independently and in any execution order.
- Never use private or unlicensed photographs, real users' face images, secrets or live personal data as fixtures.

## Priority test matrix

| Area | Test expectations |
| --- | --- |
| Engine orchestration | Configuration section order, unknown method, import-before/export-after, missing metadata. |
| Detection | Category-filtered source regions, zero/multiple faces, crop-to-page geometry, landmark ordering, confidence, empty crop. |
| Face assignment | Single/batch identity association, missing/invalid responses, no-name case, `max_people`, sequential/page/document processing modes. |
| Entity matching | No name, one/many/zero candidates, disambiguation failure, entity creation, HTTP failure; characterize current create-on-ambiguous-result behavior before modifying it. |
| ALTO writer | Face blocks, `TAGREFS`, MODS/person ID, five landmarks, namespaces, processing metadata, unrelated OCR/AnnoPage preservation. |
| PAGE writer | `ImageRegion`, `Coords`, JSON `custom` data, source relation. Explicitly track the current reader/writer mismatch instead of asserting a working round trip. |
| App adapter | Synthetic document/page/face payloads, missing ID/name/library, failed requests, partial export, placeholder vector semantics. |
| DocAPI worker | Job arguments, XML input choices, output folder, subprocess nonzero exit/failure propagation. |

Maintain small fixtures such as `tests/resources/alto_with_face_source.xml`,
`tests/resources/page_with_face_source.xml`, and matching synthetic `<page-id>.jpg`.
Include empty, multi-face, caption/OCR, unknown identity and previously
annotated cases. Where XML timestamps or UUIDs vary, compare structure or
inject deterministic values instead of comparing raw file bytes.

## Verification levels

1. **Unit:** engine and serializer behavior with fake dependencies; default offline.
2. **Contract/integration:** temporary directories and synthetic XML; stubbed app HTTP responses and job wrapper.
3. **Optional live evaluation:** explicit opt-in, disposable infrastructure, configured models/provider, no production data. Never a default PR gate.

Once pytest and a declared environment are introduced, the desired command is:

~~~bash
python -m pytest -q
~~~

This is **not yet an established passing command in this repository**. CI should install reproducible dependencies, run the real suite, and fail on errors or unexpectedly zero collected tests. PR descriptions must report checks actually run, skipped/blocked checks and reasons, and any separately authorized live/manual evaluation.
