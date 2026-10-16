# Instructions for AI coding agents

PeopleGator is a **Python document-processing tool**, not the PeopleGatorApp web application. These instructions apply to Codex and other coding agents. Before changes, read [README.md](README.md), [Architecture](docs/ARCHITECTURE.md), and the relevant technical guides.

## GitHub development workflow

1. Start from an existing GitHub issue. Read its scope, acceptance criteria, affected callers and related PRs. Do not invent unclear identity-matching or data-format requirements.
2. Create an issue-specific branch from the **current `develop`**, unless the issue names another base. Name it `issue/<number>-short-description`. Do not commit to `develop` or `main` directly.
3. Change only what is necessary, preserving unrelated work. Commit coherent, reviewable units.
4. Write regression tests for behavior changes. Run suitable tests and inspect output contracts. Report **actual** checks and skipped checks accurately; do not claim missing tests passed.
5. Push the issue branch and open a PR **targeting `develop`**. Link the issue, summarize the implementation, include test evidence and explain data/API/XML compatibility effects. Mark incomplete work as a draft.
6. Address CI and review feedback on the same branch. **Never merge, deploy, touch production data, or alter branch protection without explicit authorization.**

## Technical boundaries

- Use the existing `PeopleGatorDocument`, `PeopleGatorPageLayout`, `DocumentParser` and `DocumentProcessingEngine` pipeline. Extend the configured engine factory instead of adding a competing processing architecture.
- Keep face recognition/assignment/matching in `people_gator/engines/`; document layout and XML in `people_gator/core/layout.py`; PeopleGatorApp HTTP calls in `people_gator/core/db.py`; and DocAPI job concerns in `processing_api/`.
- **Detected face, LLM-proposed name and PeopleGatorApp entity ID are different data concepts.** Do not fabricate a resolved identity, confidence, or embedding.
- Preserve page/region IDs, bounding boxes, landmark coordinates, OCR text, source-region relationships, namespaces, XML tags and existing metadata unless the issue explicitly authorizes a contract change.
- Prefer existing upstream abstractions: [AnnoPage](https://github.com/LIBCAS/AnnoPage), [pero-ocr](https://github.com/DCGM/pero-ocr), [DocAPI](https://github.com/DCGM/DocAPI), and [PeopleGatorApp](https://github.com/DCGM/PeopleGatorApp). They are separate repositories. Do not copy frontend conventions, database models or unrelated deployment systems into this repository.
- Use synthetic images/identities and fake ML, LLM and HTTP responses in ordinary tests. No real private scans, paid inference, GPU/model downloads, shared or production databases without explicit authorization. Never commit credentials, model weights or private images.
- Document existing limitations rather than implying incomplete XML import, app synchronization or worker error handling is reliable. See [Output formats](docs/OUTPUT_FORMATS.md) and [Testing](docs/TESTING.md).

## Handoff

Report issue and branch/PR links, changed behavior, tests actually run, skipped checks, output/API impacts and remaining risks. Update relevant docs whenever an externally observable contract changes.
