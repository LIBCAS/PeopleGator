# Output formats

PeopleGator enriches document annotations. The main representations are ALTO XML and PAGE XML. The examples in the document show the intended structure of the enriched output. The actual output may vary depending on the processing configuration, engine versions and document content.

## ALTO XML

```xml
<alto>
  <Tags>
    <NamedEntityTag LABEL="person" DESCRIPTION="Karel Čapek" ID="person_001">
      <XmlData>
        <mods:mods ID="MODS_PERSON_0001" xmlns:mods="http://www.loc.gov/mods/v3">
          <mods:name type="personal" authority="peoplegator">
            <mods:namePart>Karel Čapek</mods:namePart>
            <mods:nameIdentifier type="peoplegator">uuid:ed8bae46-adff-4c10-81d7-2b03c210cc3e</mods:nameIdentifier>
            <mods:nameIdentifier type="wikidata">Q155855</mods:nameIdentifier>
            <mods:nameIdentifier type="nacr">jk01021023</mods:nameIdentifier>
          </mods:name>
          <mods:recordInfo>
            <mods:recordCreationDate encoding="iso8601">2024-10-21T18:31:43</mods:recordCreationDate>
            <mods:recordChangeDate encoding="iso8601">2026-08-12T09:24:36</mods:recordChangeDate>
            <mods:recordContentSource>PeopleGator</mods:recordContentSource>
            <mods:descriptionStandard>StandardNDK</mods:descriptionStandard>
            <mods:recordOrigin>machine-generated</mods:recordOrigin>
            <mods:recordInfoNote type="confidence">0.614</mods:recordInfoNote>
            <mods:recordInfoNote type="model.entity-linking">peoplegator-linking-0.1</mods:recordInfoNote>
            <mods:recordIdentifier source="peoplegator">uuid:e41b380b-e1f9-457b-a4c8-50db3a06328b</mods:recordIdentifier>
          </mods:recordInfo>
        </mods:mods>
      </XmlData>
    </NamedEntityTag>
    <LayoutTag TYPE="Structural" DESCRIPTION="Karel Čapek" ID="face_002" LABEL="face">
      <XmlData>
        <mods:mods ID="MODS_PICT_0002" xmlns:mods="http://www.loc.gov/mods/v3">
          <mods:physicalDescription>
            <mods:extent unit="pixels">80x80</mods:extent>
          </mods:physicalDescription>
          <mods:typeOfResource>person faces</mods:typeOfResource>
          
          <mods:genre altRepGroup="genre-1">face</mods:genre>
          <mods:genre lang="eng" altRepGroup="genre-1">face</mods:genre>
          <mods:genre lang="cze" altRepGroup="genre-1">obličej</mods:genre>
          
          <mods:relatedItem otherType="info" IDREF="MODS_PERSON_0001" />
          <mods:relatedItem type="host" IDREF="MODS_PICT_0001" />

          <mods:identifier type="uuid">uuid:4812610d-85c3-4400-af58-dce19d9e8a5f</mods:identifier>
          
          <mods:recordInfo>
            <mods:recordCreationDate>2024-10-21T18:31:43</mods:recordCreationDate>
            <mods:recordContentSource>PeopleGator</mods:recordContentSource>
            <mods:descriptionStandard>StandardNDK</mods:descriptionStandard>
            <mods:recordOrigin>machine-generated</mods:recordOrigin>
            <mods:recordInfoNote type="confidence">0.879</mods:recordInfoNote>
            <mods:recordInfoNote type="model.detection">peoplegator-face-detector-0.1</mods:recordInfoNote>
            <mods:languageOfCataloging>
            <mods:languageTerm authority="iso639-2b">eng</mods:languageTerm>
            <mods:languageTerm authority="iso639-2b">cze</mods:languageTerm>
            </mods:languageOfCataloging>
          </mods:recordInfo>
        </mods:mods>
        <pg:people-gator>
          <pg:key-points>
            <pg:points key="left-eye" x="62.00" y="7.66" unit="pixels" />
            <pg:points key="right-eye" x="68.20" y="7.66" unit="pixels" />
            <pg:points key="nose" x="64.23" y="4.20" unit="pixels" />
            <pg:points key="left-mouth-corner" x="63.26" y="4.00" unit="pixels" />
            <pg:points key="right-mouth-corner" x="65.73" y="4.00" unit="pixels" />
          </pg:key-points>
        </pg:people-gator>
      </XmlData>
    </LayoutTag>
    <LayoutTag TYPE="Structural" ID="photograph_001" LABEL="photograph">
      <XmlData>
        <mods:mods ID="MODS_PICT_0001" version="3.8" xmlns:mods="http://www.loc.gov/mods/v3">
          <mods:typeOfResource>still image</mods:typeOfResource>
          <mods:genre altRepGroup="genre-1">photograph</mods:genre>
          <mods:genre altRepGroup="genre-1" lang="eng">photograph</mods:genre>
          <mods:genre altRepGroup="genre-1" lang="cze">fotografie</mods:genre>
          <mods:physicalDescription>
            <mods:extent unit="pixels">583x820</mods:extent>
          </mods:physicalDescription>

          <mods:identifier type="uuid">uuid:4812610d-85c3-4400-af58-dce19d9e8a2f</mods:identifier>

          <mods:recordInfo>
            <mods:recordCreationDate>2024-10-21T18:31:43</mods:recordCreationDate>
            <mods:recordContentSource>Orbis Pictus</mods:recordContentSource>
            <mods:descriptionStandard>StandardNDK</mods:descriptionStandard>
            <mods:recordOrigin>machine-generated</mods:recordOrigin>
            <mods:recordInfoNote type="model.element-detection">anno-page-objects-3.0</mods:recordInfoNote>
            <mods:recordInfoNote type="confidence">0.879</mods:recordInfoNote>
            <mods:recordIdentifier source="orbis-pictus">uuid:e41b380b-e1f9-457b-a4c8-50db9a06329a</mods:recordIdentifier>
            <mods:languageOfCataloging>
            <mods:languageTerm authority="iso639-2b">eng</mods:languageTerm>
            <mods:languageTerm authority="iso639-2b">cze</mods:languageTerm>
            </mods:languageOfCataloging>
          </mods:recordInfo>
        </mods:mods>
      </XmlData>
    </LayoutTag>
    <!-- Rest of the tags... -->
  </Tags>
  <Layout>
    <Page ID="P0001" PHYSICAL_IMG_NR="1" HEIGHT="2128" WIDTH="1500">
    <TopMargin ID="P0001_TM0001" HEIGHT="85" WIDTH="1500" VPOS="0" HPOS="0" />
    <LeftMargin ID="P0001_LM0001" HEIGHT="2128" WIDTH="83" VPOS="0" HPOS="0" />
    <RightMargin ID="P0001_RM0001" HEIGHT="2128" WIDTH="0" VPOS="0" HPOS="1500" />
    <BottomMargin ID="P0001_BM0001" HEIGHT="0" WIDTH="1500" VPOS="2128" HPOS="0" />
    <PrintSpace ID="P0001_PS0001" HEIGHT="2042" WIDTH="1416" VPOS="85" HPOS="83">
      <ComposedBlock ID="P0001_CB0001" TYPE="Photograph" HEIGHT="820" WIDTH="583" VPOS="577" HPOS="486" TAGREFS="photograph_001">
        <GraphicalElement ID="P0001_GE0001" HEIGHT="820" WIDTH="583" VPOS="578" HPOS="486" />
      </ComposedBlock>
      <ComposedBlock ID="P0001_CB0002" TYPE="Face" HEIGHT="30" WIDTH="30" VPOS="600" HPOS="500" TAGREFS="person_001 face_002">
        <GraphicalElement ID="P0001_GE0002" HEIGHT="30" WIDTH="30" VPOS="600" HPOS="500" />
      </ComposedBlock>
      <!-- Rest of the page content... -->
    </PrintSpace>
  </Layout>
</alto>
```

In this example, the page contains a photograph (`ComposedBlock` with a `TYPE` of `"Photograph"`) and a detected face (`ComposedBlock` with a `TYPE` of `"Face"`). The photograph is linked to a `LayoutTag` that describes the image, while the face contains references to the corresponding `NamedEntityTag` and `LayoutTag`. The `NamedEntityTag` includes `MODS` metadata for the identified person, including name parts and identifiers. The `LayoutTag` for the face includes `MODS` metadata and `peoplegator` key points for facial landmarks. The responsibility of the PeopleGator system is to enrich the document with the face information (its ComposedBlock, LayoutTag, and NamedEntityTag).

## PAGE XML

TODO
