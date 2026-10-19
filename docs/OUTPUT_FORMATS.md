# Output formats

PeopleGator enriches document layouts with face regions, person identities, facial landmarks, and processing metadata. ALTO XML and PAGE XML are the primary formats. The examples below use one photograph with a detected face associated with Karel Čapek; identifiers and dates are illustrative.

## ALTO XML

`PeopleGatorFaceRegionLayout.to_altoxml()` creates a `ComposedBlock TYPE="Face"` with a nested `GraphicalElement`. The block's `TAGREFS` points to the face `LayoutTag`. The face tag contains MODS references to the person `NamedEntityTag` and, when available, the source photograph.

```xml
<alto xmlns="http://www.loc.gov/standards/alto/ns-v4#">
  <Description>
    <MeasurementUnit>pixel</MeasurementUnit>
    <sourceImageInformation><fileName>P0001.jpg</fileName></sourceImageInformation>
    <!-- Existing OCR and PeopleGator processing information -->
  </Description>
  <Tags>
    <!-- Photograph annotation already present in the source ALTO -->
    <LayoutTag TYPE="Structural" ID="photograph_001" LABEL="photograph">
      <XmlData>
        <mods:mods xmlns:mods="http://www.loc.gov/mods/v3" ID="MODS_PICT_0001">
          <mods:genre>photograph</mods:genre>
        </mods:mods>
      </XmlData>
    </LayoutTag>

    <!-- Face annotation added by PeopleGator -->
    <LayoutTag TYPE="Structural" ID="face_001" LABEL="face">
      <XmlData>
        <mods:mods xmlns:mods="http://www.loc.gov/mods/v3" ID="MODS_FACE_0001">
          <mods:physicalDescription>
            <mods:extent unit="pixels">80x80</mods:extent>
          </mods:physicalDescription>
          <mods:typeOfResource>person faces</mods:typeOfResource>
          <mods:genre altRepGroup="genre-1">face</mods:genre>
          <mods:genre lang="eng" altRepGroup="genre-1">face</mods:genre>
          <mods:genre lang="cze" altRepGroup="genre-1">obličej</mods:genre>
          <mods:relatedItem otherType="info" IDREF="MODS_PERSON_0001"/>
          <mods:relatedItem type="host" IDREF="MODS_PICT_0001"/>
          <mods:identifier type="uuid">uuid:4812610d-85c3-4400-af58-dce19d9e8a5f</mods:identifier>
          <mods:recordInfo>
            <mods:recordCreationDate>2026-10-19T12:00:00+00:00</mods:recordCreationDate>
            <mods:recordContentSource>PeopleGator</mods:recordContentSource>
            <mods:descriptionStandard>StandardNDK</mods:descriptionStandard>
            <mods:recordOrigin>machine-generated</mods:recordOrigin>
            <mods:recordInfoNote type="confidence">0.879</mods:recordInfoNote>
            <mods:recordInfoNote type="model.face-detection">yolo</mods:recordInfoNote>
            <mods:recordIdentifier source="AnnoPage">uuid:4812610d-85c3-4400-af58-dce19d9e8a5f</mods:recordIdentifier>
            <mods:languageOfCataloging>
              <mods:languageTerm authority="iso639-2b">eng</mods:languageTerm>
              <mods:languageTerm authority="iso639-2b">cze</mods:languageTerm>
            </mods:languageOfCataloging>
          </mods:recordInfo>
        </mods:mods>
        <pg:peoplegator xmlns:pg="https://orbis.lib.cas.cz/ns/people-gator">
          <pg:key-points>
            <pg:points key="left-eye" x="525.00" y="625.00" unit="pixels"/>
            <pg:points key="right-eye" x="555.00" y="625.00" unit="pixels"/>
            <pg:points key="nose" x="540.00" y="644.00" unit="pixels"/>
            <pg:points key="left-mouth-corner" x="530.00" y="660.00" unit="pixels"/>
            <pg:points key="right-mouth-corner" x="550.00" y="660.00" unit="pixels"/>
          </pg:key-points>
        </pg:peoplegator>
      </XmlData>
    </LayoutTag>

    <!-- Person identity added by PeopleGator -->
    <NamedEntityTag ID="person_001" LABEL="person">
      <XmlData>
        <mods:mods xmlns:mods="http://www.loc.gov/mods/v3" ID="MODS_PERSON_0001">
          <mods:name type="personal" authority="peoplegator">
            <mods:namePart>Karel Čapek</mods:namePart>
            <mods:nameIdentifier type="peoplegator">uuid:ed8bae46-adff-4c10-81d7-2b03c210cc3e</mods:nameIdentifier>
            <mods:nameIdentifier type="wikidata">Q155855</mods:nameIdentifier>
          </mods:name>
          <mods:recordInfo>
            <mods:recordCreationDate>2026-10-19T12:00:00+00:00</mods:recordCreationDate>
            <mods:recordContentSource>PeopleGator</mods:recordContentSource>
            <mods:descriptionStandard>StandardNDK</mods:descriptionStandard>
            <mods:recordOrigin>machine-generated</mods:recordOrigin>
            <mods:recordIdentifier source="AnnoPage">uuid:e41b380b-e1f9-457b-a4c8-50db3a06328b</mods:recordIdentifier>
            <mods:languageOfCataloging>
              <mods:languageTerm authority="iso639-2b">eng</mods:languageTerm>
              <mods:languageTerm authority="iso639-2b">cze</mods:languageTerm>
            </mods:languageOfCataloging>
          </mods:recordInfo>
        </mods:mods>
      </XmlData>
    </NamedEntityTag>
  </Tags>
  <Layout>
    <Page ID="P0001" PHYSICAL_IMG_NR="1" HEIGHT="2128" WIDTH="1500">
      <PrintSpace ID="P0001_PS0001" HEIGHT="2042" WIDTH="1416" VPOS="85" HPOS="83">
        <ComposedBlock ID="P0001_CB0001" TYPE="Photograph"
                       HEIGHT="820" WIDTH="583" VPOS="577" HPOS="486"
                       TAGREFS="photograph_001">
          <GraphicalElement ID="P0001_GE0001"
                            HEIGHT="820" WIDTH="583" VPOS="577" HPOS="486"/>
        </ComposedBlock>
        <ComposedBlock ID="P0001_CB0002" TYPE="Face"
                       HEIGHT="80" WIDTH="80" VPOS="600" HPOS="500"
                       TAGREFS="face_001">
          <GraphicalElement ID="P0001_GE0002"
                            HEIGHT="80" WIDTH="80" VPOS="600" HPOS="500"/>
        </ComposedBlock>
      </PrintSpace>
    </Page>
  </Layout>
</alto>
```

**Code comparison:** The face block references only `face_001` in `TAGREFS`; the person is linked through `mods:relatedItem IDREF="MODS_PERSON_0001"`. The face MODS ID uses the `MODS_FACE` prefix. The bounding box, metadata extent, and all five landmarks now share the same page-image coordinates. The example has the ALTO namespace, the `pg` namespace, and matching closing elements.

The source photograph is supplied by the document/AnnoPage layout. The writer also adds processing records and generated MODS metadata; the example concentrates on the face and identity information.

## PAGE XML

`PeopleGatorFaceRegionLayout.to_pagexml()` creates an `ImageRegion` with polygon coordinates and JSON stored in its `custom` attribute. The JSON includes detection data, five landmark positions, person identity, and the source-region ID.

```xml
<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15/pagecontent.xsd">
  <Metadata>
    <Creator>Pero OCR</Creator>
    <Created>2026-10-19T12:00:00+00:00</Created>
    <LastChange>2026-10-19T12:00:00+00:00</LastChange>
    <MetadataItem type="processingStep"
                  name="Face detection and analysis and named entity recognition"
                  value="PeopleGator v0.0.1"
                  date="2026-10-19T12:00:00+00:00"/>
  </Metadata>
  <Page imageFilename="P0001" imageWidth="1500" imageHeight="2128">
    <!-- Source region from the document layout -->
    <ImageRegion id="photograph_001">
      <Coords points="486,577 1069,577 1069,1397 486,1397"/>
    </ImageRegion>

    <!-- Face region added by PeopleGator -->
    <ImageRegion id="face_001"
      custom='{
        "category": "face",
        "detection_confidence": 0.879,
        "metadata": {
          "tag_id": "face_001",
          "mods_id": "MODS_FACE_0001",
          "mods_uuid": "4812610d-85c3-4400-af58-dce19d9e8a5f",
          "record_identifier": "4812610d-85c3-4400-af58-dce19d9e8a5f",
          "used_ai_models": {"model.face-detection": "yolo"},
          "creation_date_time": "2026-10-19T12:00:00+00:00",
          "confidence": 0.879,
          "left_eye_position": {"x": 525, "y": 625},
          "right_eye_position": {"x": 555, "y": 625},
          "nose_position": {"x": 540, "y": 644},
          "left_mouth_corner_position": {"x": 530, "y": 660},
          "right_mouth_corner_position": {"x": 550, "y": 660},
          "page_identity": {
            "tag_id": "person_001",
            "mods_id": "MODS_PERSON_0001",
            "mods_uuid": "e41b380b-e1f9-457b-a4c8-50db3a06328b",
            "record_identifier": "e41b380b-e1f9-457b-a4c8-50db3a06328b",
            "used_ai_models": {},
            "creation_date_time": "2026-10-19T12:00:00+00:00",
            "confidence": null,
            "identity": {
              "name": "Karel Čapek",
              "peoplegator_id": "ed8bae46-adff-4c10-81d7-2b03c210cc3e",
              "other_ids": {"wikidata": "Q155855"}
            }
          }
        },
        "source_region": "photograph_001"
      }'>
      <Coords points="500,600 500,680 580,680 580,600 500,600"/>
    </ImageRegion>
  </Page>
</PcGts>
```

The JSON is formatted across lines and enclosed in single-quoted XML attribute delimiters for readability. The writer serializes it with `json.dumps` and escapes the quotes in the resulting XML. The field names and nested objects come from `PeopleGatorFaceMetadata.to_dict()` and `PeopleGatorPageIdentity.to_dict()`. The optional `type` attribute is emitted when a face region has `region_type`.

## XML import and repeat processing

The ALTO face readers and `altoxml_load_regions` hook are pending implementation. The PAGE writer currently emits `ImageRegion`, while the PAGE face import hook searches for `CustomRegion[@type='face']`. The ALTO cleanup helper `remove_peoplegator_elements()` currently preserves the input unchanged. Completing face round-trip and repeated-enrichment behavior is tracked in [TODO.md](TODO.md) and [Testing](TESTING.md).
