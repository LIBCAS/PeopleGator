# Output formats

Face annotations are represented by `PeopleGatorFaceRegionLayout` and `PeopleGatorFaceMetadata` in `people_gator/core/layout.py`. Each face carries a polygon and confidence, source-region reference, five facial landmarks, an optional proposed person name and PeopleGatorApp entity ID, tag/MODS IDs, and optional model provenance. Geometry and landmarks use page-image pixel coordinates.

## ALTO XML

`PeopleGatorDocument.to_altoxml()` writes one `<page-id>.xml` file per page, defaulting to `ALTOVersion.ALTO_v4_4`. For a face the writer creates:
- `ComposedBlock TYPE="Face"` containing `GraphicalElement`, with its bounding rectangle;
- a `LayoutTag` labeled `face`, attached with `TAGREFS`, containing MODS size, relations, provenance and landmarks;
- a `NamedEntityTag` labeled `person` with MODS identity metadata, including person name and optional `peoplegator` identifier.

MODS uses `http://www.loc.gov/mods/v3`; landmark data uses `https://orbis.lib.cas.cz/ns/people-gator` (`pg`). A PeopleGator processing record is appended. When a source ALTO document is available, the writer edits its XML tree and should preserve unrelated OCR and AnnoPage content; this preservation is not yet backed by repository tests.

## PAGE XML

`PeopleGatorFaceRegionLayout.to_pagexml()` writes an `ImageRegion` containing `Coords points`. Its `custom` attribute is JSON with `category`, `detection_confidence`, serialized `metadata` (including identity/landmarks), and source-region ID. A processing-step metadata entry is also added. The output is a description of **current writer behavior**, not a guarantee of external PAGE compatibility or successful readback.

## Files and app export

The folder CLI supports:
- `--output-alto-path`: `<page-id>.xml` ALTO files;
- `--output-xml-path`: `<page-id>.xml` PAGE files;
- `--output-render-path`: optional `<page-id>.jpg` annotated images.

With `--export-to-app`, the HTTP adapter sends documents, pages containing faces, face records, page JPEGs and selected layout data to the separate PeopleGatorApp API, provided document ID, name and library are available. The adapter passes the person entity ID if one exists. This is API persistence, **not a local PeopleGator database**.

**Current placeholder:** `DatabaseApiService.create_face()` includes model identifier `vit_small_patch8_gap_112.cosface_ms1mv3` with a **512-element zero vector**. It does *not* compute or export a real face embedding. Do not document embedding-based recognition as implemented based on this field.

## Known implementation limitations

- `PeopleGatorFaceMetadata.from_altoxml()` and `PeopleGatorFaceRegionLayout.from_altoxml()` raise `NotImplementedError`; the ALTO face-region load hook is empty. Existing PeopleGator faces are not reliably read from ALTO.
- The PAGE writer emits `ImageRegion`, but the current PAGE face import hook searches for `CustomRegion[@type='face']`. **PAGE face round trips are not established.**
- `remove_peoplegator_elements()` currently returns the ALTO tree unchanged. Re-processing ALTO output could duplicate annotations; idempotent export is not implemented.
- XML schema validation, uniqueness on reruns, geometry/identity preservation and application export consistency require synthetic regression tests.

When changing any format, explicitly review compatibility and add before/after XML fixtures and structural assertions. See [Testing](TESTING.md).
