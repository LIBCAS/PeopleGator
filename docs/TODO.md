# Development TODO

This roadmap lists processing-related development work identified from the current code and PeopleGator system design. Create GitHub issues with acceptance criteria for individual tasks.

## Development infrastructure

- [x] Add `pyproject.toml`, declared dependencies and CLI entry points (issue #25).
- [x] Introduce synthetic fixtures and automated tests (see [Testing](TESTING.md)).
- [ ] Add GitHub Actions CI.

## Processing and annotation

- [ ] Implement ALTO face-annotation import and align PAGE face reader/writer formats.
- [ ] Make repeated ALTO enrichment replace existing PeopleGator annotations consistently.
- [ ] Test unknown, ambiguous and verified person-identity assignments.
- [x] Calculate [face embeddings](PROCESSING.md#face_embedding) in an optional stage.
- [ ] Integrate similarity-based entity matching.
- [x] Detect and cluster OCR person mentions and link them to document/app identities (tracked under [#33](https://github.com/LIBCAS/PeopleGator/issues/33)).
- [ ] Complete text-mention ALTO/PAGE import/export and cluster persistence ([#33](https://github.com/LIBCAS/PeopleGator/issues/33)).

## API and re-export

- [x] Propagate worker subprocess failures (issue #29).
- [ ] Verify worker job result files.
- [ ] Validate PeopleGatorApp import/export contracts and repeated processing.
- [ ] Implement the corrected-identity re-export flow described in [Architecture](ARCHITECTURE.md).

See [Processing](PROCESSING.md), [Output formats](OUTPUT_FORMATS.md), and [Testing](TESTING.md) for context.
