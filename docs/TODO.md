# Development TODO

This roadmap lists processing-related development work identified from the current code and PeopleGator system design. Create GitHub issues with acceptance criteria for individual tasks.

## Development infrastructure

- [ ] Add `pyproject.toml`, declared dependencies and CLI entry points.
- [ ] Introduce synthetic fixtures, automated tests, and GitHub Actions CI.

## Processing and annotation

- [ ] Implement ALTO face-annotation import and align PAGE face reader/writer formats.
- [ ] Make repeated ALTO enrichment replace existing PeopleGator annotations consistently.
- [ ] Test unknown, ambiguous and verified person-identity assignments.
- [ ] Calculate face embeddings and integrate similarity-based entity matching.
- [ ] Expand person mentions in OCR text and link them to page/document entities.

## API and re-export

- [ ] Propagate worker subprocess failures and verify job result files.
- [ ] Validate PeopleGatorApp import/export contracts and repeated processing.
- [ ] Implement the corrected-identity re-export flow described in [Architecture](ARCHITECTURE.md).

See [Processing](PROCESSING.md), [Output formats](OUTPUT_FORMATS.md), and [Testing](TESTING.md) for context.
