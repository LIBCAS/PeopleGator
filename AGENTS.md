# Instructions for AI coding agents

PeopleGator processes digitized documents to detect faces, propose and resolve person identities, and annotate ALTO/PAGE XML. The processing software also communicates with the PeopleGatorApp person/face database and participates in DocAPI-managed document jobs.

Before changing code, read [README.md](README.md), the applicable guide in `docs/`, the complete GitHub issue, affected callers and existing tests.

## GitHub development workflow

1. Start with a GitHub issue containing a clear problem, scope and verifiable acceptance criteria. Confirm open questions about identity resolution, confidence and XML semantics with the maintainer.
2. Branch from the latest `develop` (unless an issue specifies another base), using `issue/<number>-short-description`. Keep `develop` and `main` changes reviewable through pull requests.
3. Make focused changes in coherent commits and preserve unrelated work.
4. Add and run regression tests for changed behavior, using synthetic data and controlled dependencies. Record checks actually run, their outcomes and remaining verification work.
5. Push the issue branch and open a PR targeting `develop`; link the issue, describe resulting behavior, document XML/API changes and include test evidence. Use a draft PR while implementation or validation is in progress.
6. Resolve CI and review findings. Merge, deployments and modifications to production data require explicit authorization.

## Processing architecture

- Extend the existing `PeopleGatorDocument`, `PeopleGatorPageLayout`, `DocumentParser` and `DocumentProcessingEngine` interfaces. Processing engines are selected by ordered `[ENGINE_*]` INI sections.
- Keep face detection and identity inference in `people_gator/engines/`; layout and serialization in `people_gator/core/layout.py`; PeopleGatorApp API communication in `people_gator/core/db.py`; and DocAPI job integration in `processing_api/`.
- Use shared types from [pero-ocr](https://github.com/DCGM/pero-ocr) and [AnnoPage](https://github.com/LIBCAS/AnnoPage). Consult their relevant interfaces when changing OCR layout, graphical-region or XML behavior.
- Implement person lookup, persistence and corrected-assignment import against documented PeopleGatorApp HTTP contracts. DocAPI manages the client/worker job lifecycle. See [Architecture](docs/ARCHITECTURE.md).

## Entity and data contracts

- Distinguish **occurrences** (face regions or name spans) from **entities** (people). A face occurrence can have a proposed name and an optional resolved person ID. Separate algorithmic proposals from librarian-verified assignments.
- Maintain page-relative bounding boxes, facial landmark coordinates, stable document/page/region IDs, source-region references, text spans, namespaces and ALTO/PAGE metadata. Preserve existing OCR/AnnoPage annotations during enrichment.
- The intended workflow includes matching against existing people, introducing provisional entities where appropriate, librarian corrections, and re-export with revised assignments. Identify planned behavior separately from implemented code.
- Record the model used, evidence/confidence when available, and the actual outcome of service calls. Keep face embeddings tied to their real generation model and geometry conventions.
- Write small, deterministic tests using synthetic pages, generated names, fake model outputs and isolated HTTP responses. Run live inference and infrastructure tests only with explicitly approved credentials and disposable data.
- Keep secrets, downloaded checkpoints and personal documents in approved external locations rather than commits.

## Read before editing

- [Architecture](docs/ARCHITECTURE.md): module ownership and end-to-end job flow.
- [Processing](docs/PROCESSING.md): input, engine order and person-occurrence lifecycle.
- [Output formats](docs/OUTPUT_FORMATS.md): ALTO/PAGE structures, app persistence and re-export goals.
- [Testing](docs/TESTING.md): regression matrix, fixtures and validation plans.

## Handoff

Report issue/branch/PR links, changed functionality, test commands and outcomes, changed external contracts, pending tests and decisions needed for review. Keep the documentation synchronized with new supported processing behavior.
