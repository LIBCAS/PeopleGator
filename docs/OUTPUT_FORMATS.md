# Output formats

PeopleGator writes enriched document annotations and communicates face/person records to the PeopleGatorApp API. The XML representation supports page-level coordinates and links image occurrences to their identities.

## Face and identity data

`PeopleGatorFaceRegionLayout` holds a face polygon, detection confidence and source-region reference. `PeopleGatorFaceMetadata` records five landmarks (left/right eyes, nose and left/right mouth corners), tag/MODS identifiers, model provenance and an associated `PeopleGatorPageIdentity`. A person identity can contain a proposed name, a `peoplegator_id` and other identifiers. Current in-memory landmark coordinates are page-image pixels.

The broader system design also describes `Entity`, `Face`, `Source`, `DocumentMention` and `PageMention` records. Face occurrences link to at most one person; text occurrences refer to their source document/page and person identity. The occurrence and source relationships should be preserved when exchanging results with the app API.

## ALTO XML (current implementation)

`PeopleGatorDocument.to_altoxml()` writes `<page-id>.xml` for each page, defaulting to `ALTOVersion.ALTO_v4_4`. Each face is serialized through:
- a `ComposedBlock` with `TYPE="Face"`, including `GraphicalElement` with face bounds;
- a `LayoutTag` labeled `face`, referenced by `TAGREFS`, with MODS face description, provenance and five landmarks;
- a `NamedEntityTag` labeled `person` containing MODS identity data.

MODS uses `http://www.loc.gov/mods/v3`; PeopleGator landmark extensions use `https://orbis.lib.cas.cz/ns/people-gator`. The writer adds processing metadata and appends face annotations to the source ALTO tree. The intended consumer contract preserves existing text and AnnoPage annotations while enriching the page.

The system design identifies ALTO XML as the interchange format for person occurrences to downstream digital libraries, including Kramerius/ČDK. XML metadata should retain stable links to identities and face regions across processing and review.

## PAGE XML (current implementation)

`PeopleGatorFaceRegionLayout.to_pagexml()` writes an `ImageRegion` with a polygon in `Coords points`. The `custom` attribute contains JSON with `category`, `detection_confidence`, full face `metadata` and `source_region`. The writer also adds page processing-step metadata.

## File and API outputs

The local CLI writes `<page-id>.xml` under `--output-alto-path` or `--output-xml-path`, plus optional annotated `<page-id>.jpg` under `--output-render-path`.

With `--export-to-app`, `DatabaseApiService` sends document, page and face records and uploads page images/layouts to the PeopleGatorApp API. The document metadata must contain an ID, name and library for this export. Existing person-entity IDs are included with faces when available.

The current face POST payload includes the model identifier `vit_small_patch8_gap_112.cosface_ms1mv3` and a **512-element zero vector** as a placeholder embedding. Generating face embeddings and similarity-based identification are planned processing improvements.

**Planned additional outputs:** the system design calls for accompanying structured data (including JSON), results packaged for client download, and re-exported XML reflecting librarian corrections. Their exact sidecar/ZIP contracts will be specified alongside implementation.

## Planned XML compatibility and re-export work

- Complete ALTO face metadata and face-region readers, whose corresponding `from_altoxml()` methods currently raise `NotImplementedError`, and implement the `altoxml_load_regions` hook.
- Align PAGE face serialization (`ImageRegion`) with the existing reader hook looking for `CustomRegion[@type='face']`, and exercise read–write–read tests.
- Make ALTO enrichment repeatable: `remove_peoplegator_elements()` currently returns the source unchanged, so duplicate prevention requires implementation and tests.
- Define XML schema validation, identifier stability and preservation of source OCR and AnnoPage metadata across consecutive processing runs.
- Support the planned re-export pipeline: ingest corrected entity links from the PeopleGatorApp API and generate revised ALTO annotations from the client's original ALTO and stored results.

See [Testing](TESTING.md) for synthetic fixture cases.
