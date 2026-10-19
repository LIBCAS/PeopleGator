# Testing strategy

PeopleGator development should maintain deterministic regression coverage for processing engines, XML annotations, person-entity mapping and asynchronous job handling.

## Test infrastructure roadmap

The initial repository documentation task establishes the testing contract. The next development steps are to introduce Python packaging/test dependencies, a `tests/` directory with fixtures, and CI checks for pull requests. The target command, once the environment and suite are configured, is:

~~~bash
python -m pytest -q
~~~

CI should install declared dependencies, collect real tests and report failures. A documentation-only change can be reviewed with structural and link checks.

## Principles

- Use small synthetic page images, fabricated names and matching ALTO/PAGE XML fixtures.
- Inject deterministic YOLO predictions, LLM Responses output and PeopleGatorApp/DocAPI HTTP responses for fast CPU tests.
- Run integration tests against isolated, disposable stores and explicitly configured providers. Keep private scans, credentials and real personal data outside fixtures.
- Verify actual serialized tags, coordinates, identity links and input-preservation behavior. Record tests run and outcomes in every implementation PR.

## Coverage priorities

| Processing area | Required regression scenarios |
| --- | --- |
| CLI/document construction | INI engine ordering, image-to-page mapping, ALTO/PAGE selection, optional metadata and missing inputs. |
| Face detection | Source-region categories, coordinates translated from crops, confidence, five landmarks, empty/multiple detections. |
| LLM assignment | OCR/caption context, single and batch response mapping, `max_people`, three processing modes, failed and ambiguous predictions. |
| Entity matching | One/multiple/no person candidates, normalized names, creation of provisional people, ambiguous matching, API errors and unresolved faces. |
| Person occurrences | Consistency of face ID/source/identity links; proposed name versus verified entity ID; future text mention spans/clusters and annotations. |
| ALTO XML | `ComposedBlock`, `LayoutTag`, `NamedEntityTag`, `TAGREFS`, MODS, landmarks, namespace handling and original content preservation. |
| PAGE XML | `ImageRegion`, face polygon, JSON `custom` metadata, source-region ID and planned reader/writer consistency. |
| PeopleGatorApp API | Document/page/face creation, image/layout uploads, corrected identity import, partial failure, repeated processing and embedding payload semantics. |
| DocAPI processing | Client submission/result retrieval, input types, worker command, engine configuration, success/failure reporting and result packaging. |
| Correction/re-export (planned) | A librarian's corrected entity link is imported and appears in newly generated ALTO without changing unrelated text or face geometry. |

## Fixtures and XML assertions

Store small synthetic examples under `tests/resources/`, such as `alto_with_photo.xml`,
`page_with_photo.xml`, a matching `<page-id>.jpg`, and metadata with document ID/name/library. Include documents with zero/multiple faces, captions, OCR names, unknown identities and previously enriched regions.

Assert XML structure, namespace-qualified elements, polygon coordinates, MODS identity references, and consistent mapping to PeopleGatorApp source/face records. For timestamps and UUIDs, use injected deterministic values or structural comparisons. Add read–write–read tests for supported formats and characterize outstanding ALTO/PAGE reader work in dedicated regression cases.

## Validation and handoff

Run focused tests for each modified engine or serializer; run the full suite when the test environment is available. Record exact commands, passing/failing cases, skipped checks and any separately approved live model evaluation in the PR. Include fixture examples whenever output schemas or identity-matching rules change.
