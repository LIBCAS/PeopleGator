import os
import json
import numpy as np

from xml import etree as ET
from typing import Optional, Tuple

from pero_ocr.core.layout import RegionLayout, TextLine, ALTOVersion, create_ocr_processing_element
from anno_page.core.layout import AnnoPagePageLayout

from people_gator import globals
from people_gator.core.utils import load_image
from people_gator.core.metadata import FaceMetadata
from people_gator.core.services import DateTimeService


class PeopleGatorFaceRegionLayout(Regionlayout):
    def __init__(self,
                 id: str,
                 polygon: np.ndarray,
                 region_type: str|None = None,
                 category: str|None = None,
                 detection_confidence: float|None = None,
                 face_metadata: FaceMetadata|None = None):
        super().__init__(id=id,
                         polygon=polygon,
                         region_type=region_type,
                         category=category,
                         detection_confidence=detection_confidence)

        self.face_metadata: FaceMetadata|None = face_metadata

    def to_altoxml(self, print_space_element, tags, mods_namespace, arabic_helper, min_line_confidence,
                   print_space_coords: Tuple[int, int, int, int], version: ALTOVersion, word_splitters=["-"]) -> Tuple[int, int, int, int]:
        pass

    @classmethod
    def from_altoxml(cls, element):
        return None

    def to_pagexml(self, page_element: ET.SubElement, validate_id: bool = False):
        custom = {
            "category": self.category,
            "detection_confidence": round(self.detection_confidence, 3),
            "metadata": self.face_metadata.to_dict() if self.face_metadata is not None else None
        }

        region_element = ET.SubElement(page_element, "ImageRegion")
        region_element.attrib["id"] = self.id
        region_element.attrib["custom"] = json.dumps(custom)

        if self.region_type is not None:
            region_element.attrib["type"] = self.region_type

        coords = ET.SubElement(region_element, "Coords")
        coords.attrib["points"] = " ".join([f"{int(x)},{int(y)}" for x, y in self.polygon])

    @classmethod
    def from_pagexml(cls, region_element: ET.SubElement, page_layout=None):
        region_id = region_element.attrib["id"]
        region_type = region_element.attrib.get("type", None)

        polygon = []
        coords_element = region_element.find("Coords", region_element.nsmap)
        if coords_element is not None:
            points_str = coords_element.attrib.get("points", "")
            for point_str in points_str.split():
                x_str, y_str = point_str.split(",")
                polygon.append((float(x_str), float(y_str)))

        polygon = np.array(polygon)

        category = None
        detection_confidence = None
        face_metadata = None

        if "custom" in region_element.attrib:
            custom = json.loads(region_element.attrib["custom"])
            category = custom.get("category", None)
            detection_confidence = custom.get("detection_confidence", None)
            metadata_dict = custom.get("metadata", None)
            if metadata_dict is not None:
                face_metadata = FaceMetadata.from_dict(metadata_dict, page_layout)

        region = cls(region_id,
                     polygon=polygon,
                     region_type=region_type,
                     category=category,
                     detection_confidence=detection_confidence,
                     face_metadata=face_metadata)

        return region


class PeopleGatorTextEntity:
    def __init__(self, text: str, line: TextLine, span: tuple[int, int]):
        self.text: str = text
        self.line: TextLine = line
        self.span: tuple[int, int] = span


class PeopleGatorPageLayout(AnnoPagePageLayout):
    def __init__(self, id, page_size):
        super().__init__(id, page_size)

        self.text_entities: list[PeopleGatorTextEntity] = []

        self.from_altoxml_ended += altoxml_load_regions
        self.from_pagexml_ended += pagexml_load_regions

        self.to_altoxml_processing_added += altoxml_add_processing_step
        self.to_altoxml_regions_ended += altoxml_postprocess_lines
        self.to_pagexml_processing_added += pagexml_add_processing_step

    @property
    def faces(self):
        return [region for region in self.regions if isinstance(region, PeopleGatorFaceRegionLayout)]


class PeopleGatorTextEntityCluster:
    def __init__(self, text_entities: list[PeopleGatorTextEntity], text: str|None = None, description: str|None = None):
        self.text_entities: list[PeopleGatorTextEntity] = text_entities
        self.text: str|None = text
        self.description: str|None = description


class PeopleGatorDocument:
    def __init__(self,
                 page_layouts: list[PeopleGatorPageLayout]|None = None,
                 text_entity_clusters: list[PeopleGatorTextEntityCluster]|None = None,
                 page_images: dict[str, np.ndarray]|None = None,
                 page_images_dir: str|None = None,
                 load_images: bool = False,
                 keep_images_in_memory: bool = False):
        self.page_layouts: list[PeopleGatorPageLayout] = page_layouts if page_layouts is not None else []
        self.text_entity_clusters: list[PeopleGatorTextEntityCluster] = text_entity_clusters if text_entity_clusters is not None else []

        self.page_images = page_images if page_images is not None else {}
        self.page_images_dir: str|None = page_images_dir

        self.load_images: bool = load_images
        self.keep_images_in_memory: bool = keep_images_in_memory

        if self.load_images:
            self.load_page_images()

    def pages_iterator(self):
        if self.page_layouts:
            for page_layout in self.page_layouts:
                page_image = self.get_page_image(page_layout)
                yield page_image, page_layout

    @property
    def text_entities(self):
        text_entities = []
        for page_layout in self.page_layouts:
            text_entities.extend(page_layout.text_entities)
        return text_entities

    @property
    def faces(self):
        faces = []
        for page_layout in self.page_layouts:
            faces.extend(page_layout.faces)
        return faces

    def load_page_images(self):
        if self.page_images_dir:
            for page_layout in self.page_layouts:
                self.load_page_image(page_layout)
        else:
            raise Exception("Cannot load page images: no page_images_dir specified.")

    def load_page_image(self, page_layout):
        if self.page_images_dir:
            image_path = os.path.join(self.page_images_dir, f"{page_layout.id}.jpg")
            image = load_image(image_path)
            if self.keep_images_in_memory:
                self.page_images[page_layout.id] = image
            return image
        else:
            raise Exception(f"Cannot load page image for page '{page_layout.id}': no page_images_dir specified.")

    def get_page_image(self, page_layout, force_reload=False):
        if force_reload or page_layout.id not in self.page_images:
            page_image = self.load_page_image(page_layout)
        elif page_layout.id in self.page_images:
            page_image = self.page_images[page_layout.id]
        else:
            raise Exception(f"Cannot load page image for page '{page_layout.id}': no page_images_dir specified and image not in memory.")

        return page_image

    def from_altoxml(self, alto_dir):
        files = [file for file in os.listdir(alto_dir) if file.lower().endswith('.xml')]
        page_layouts = []

        for file in files:
            file_path = os.path.join(alto_dir, file)
            page_layout = PeopleGatorPageLayout.from_altoxml(file_path)
            page_layouts.append(page_layout)

        self.page_layouts = page_layouts

    def to_altoxml(self, output_dir, alto_version=ALTOVersion.ALTO_v4_4):
        if self.page_layouts:
            for page in self.page_layouts:
                page.to_altoxml(output_dir, alto_version=alto_version)

    def from_pagexml(self, pagexml_dir):
        files = [file for file in os.listdir(pagexml_dir) if file.lower().endswith('.xml')]
        page_layouts = []

        for file in files:
            file_path = os.path.join(pagexml_dir, file)
            page_layout = PeopleGatorPageLayout.from_pagexml(file_path)
            page_layouts.append(page_layout)

        self.page_layouts = page_layouts

    def to_pagexml(self, output_dir):
        if self.page_layouts:
            for page_layout in self.page_layouts:
                page_layout.to_pagexml(output_dir)


def altoxml_load_regions(page_layout, root):
    pass


def pagexml_load_regions(page_layout, page_tree):
    root = page_tree.getroot()
    for region_element in root.findall(".//CustomRegion[@type='face']", root.nsmap):
        region = PeopleGatorFaceRegionLayout.from_pagexml(region_element, page_layout)
        if region is not None:
            page_layout.regions.append(region)


def altoxml_add_processing_step(page_layout, description_element, alto_version=ALTOVersion.ALTO_v4_4):
    processing_element = create_ocr_processing_element(id=globals.software_name,
                                                       software_creator_str=globals.software_creator,
                                                       software_name_str=globals.software_name,
                                                       software_version_str=globals.software_version,
                                                       alto_version=alto_version)

    description_element.append(processing_element)


def pagexml_add_processing_step(page_layout, metadata: ET.Element):
    metadata_item = ET.SubElement(metadata, "MetadataItem")
    metadata_item.set("type", "processingStep")
    metadata_item.set("name", "Face detection and analysis and named entity recognition")
    metadata_item.set("value", globals.software_fullname)
    metadata_item.set("date", DateTimeService.get_datetime_now().isoformat())


def altoxml_postprocess_lines(page_layout, print_space_element, alto_version=ALTOVersion.ALTO_v4_4):
    pass
