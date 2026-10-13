import os
import cv2
import json
import numpy as np

from lxml import etree as ET
from typing import Tuple

from pero_ocr.core.layout import RegionLayout, TextLine, ALTOVersion, create_ocr_processing_element
from anno_page.core.layout import AnnoPagePageLayout, set_position_and_size, get_next_id, get_page_element, get_print_space_coords, update_print_space_and_margins
from anno_page.core.metadata import BaseMetadata as AnnoPageBaseMetadata
from anno_page.core.utils import find_or_create_tags_element, get_root_element, find_or_create_element
from anno_page.enums import Language

from people_gator import globals
from people_gator.core.utils import load_image, find_source_region_by_bounding_box
from people_gator.core.services import DateTimeService


class Position:
    def __init__(self, x: float|int, y: float|int):
        self.x = x
        self.y = y

    def __repr__(self):
        return f"Position(x={self.x}, y={self.y})"

    def to_json(self):
        return {"x": self.x, "y": self.y}

    @classmethod
    def from_json(cls, data):
        x = data.get("x")
        y = data.get("y")
        return cls(x, y)


class PeopleGatorIdentity:
    def __init__(self, name: str|None, peoplegator_id: str|None, other_ids: dict[str, str]|None = None):
        self.name: str|None = name
        self.peoplegator_id: str|None = peoplegator_id
        self.other_ids: dict[str, str]|None = other_ids

    def __repr__(self):
        return f"PeopleGatorIdentity(name={self.name}, peoplegator_id={self.peoplegator_id}, other_ids={self.other_ids})"

    def to_altoxml(self, mods, mods_namespace):
        self._add_name_element(mods, mods_namespace, self.name, self.peoplegator_id, self.other_ids)    

    def to_dict(self):
        return {
            "name": self.name,
            "peoplegator_id": self.peoplegator_id,
            "other_ids": self.other_ids
        }

    @classmethod
    def from_dict(cls, data: dict):
        name: str|None = data.get("name")
        peoplegator_id: str|None = data.get("peoplegator_id")
        other_ids: dict[str, str]|None = data.get("other_ids")

        return cls(name=name, peoplegator_id=peoplegator_id, other_ids=other_ids)
    
    @staticmethod
    def _add_name_element(mods, mods_namespace, name: str|None, peoplegator_id: str|None, other_ids: dict[str, str]|None = None):
        name_element = ET.SubElement(mods, f"{{{mods_namespace}}}name")
        name_element.attrib["type"] = "personal"
        name_element.attrib["authority"] = "peoplegator"

        if name:
            name_part = ET.SubElement(name_element, f"{{{mods_namespace}}}namePart")
            name_part.text = name

        if peoplegator_id:
            name_identifier_peoplegator = ET.SubElement(name_element, f"{{{mods_namespace}}}nameIdentifier")
            name_identifier_peoplegator.attrib["type"] = "peoplegator"
            name_identifier_peoplegator.text = f"uuid:{peoplegator_id}"

        if other_ids:
            for id_type, id_value in other_ids.items():
                name_identifier_other = ET.SubElement(name_element, f"{{{mods_namespace}}}nameIdentifier")
                name_identifier_other.attrib["type"] = id_type
                name_identifier_other.text = id_value


class PeopleGatorPageIdentity(AnnoPageBaseMetadata):
    def __init__(self,
                 tag_id: str,
                 mods_id: str,
                 identity: PeopleGatorIdentity,
                 mods_uuid: str | None = None,
                 record_identifier: str | None = None,
                 used_ai_models: dict | None = None,
                 creation_date_time=None,
                 confidence: float | None = None):
        super().__init__(tag_id,
                         mods_id,
                         mods_uuid,
                         record_identifier,
                         used_ai_models,
                         creation_date_time,
                         confidence)

        self.identity = identity

    def __repr__(self):
        return f"PeopleGatorPageIdentity(identity={self.identity}, tag_id={self.tag_id}, mods_id={self.mods_id}, mods_uuid={self.mods_uuid}, record_identifier={self.record_identifier}, used_ai_models={self.used_ai_models}, creation_date_time={self.creation_date_time}, confidence={self.confidence})"

    def to_altoxml(self, tags):
        named_entity_tag = ET.SubElement(tags, "NamedEntityTag")
        xml_data = ET.SubElement(named_entity_tag, "XmlData")

        named_entity_tag.set("ID", self.tag_id)
        named_entity_tag.set("LABEL", "person")

        mods_namespace = globals.mods_xml_namespace
        mods_xmlns = {globals.mods_xml_prefix: mods_namespace}
        mods = ET.SubElement(xml_data, f"{{{mods_namespace}}}mods", nsmap=mods_xmlns)

        mods.set("ID", self.mods_id)

        self.identity.to_altoxml(mods, mods_namespace)

        if self.creation_date_time is not None:
            creation_date_time = self.creation_date_time
        else:
            creation_date_time = DateTimeService.get_datetime_now().isoformat(timespec='seconds')

        self._add_record_info_element(mods,
                                      mods_namespace,
                                      content_source=globals.software_name,
                                      creation_date_time=creation_date_time,
                                      record_identifier=self.record_identifier,
                                      confidence=self.confidence,
                                      used_ai_models=self.used_ai_models)

    @classmethod
    def from_altoxml(cls):
        raise NotImplementedError("Not implemented yet.")

    def to_dict(self):
        result = super().to_dict()
        result.update({
            "identity": self.identity.to_dict() if self.identity is not None else None
        })

        return result

    @classmethod
    def from_dict(cls, data: dict):
        tag_id: str|None = data.get("tag_id")
        if tag_id is None:
            raise ValueError("Missing 'tag_id' in data.")

        mods_id: str|None = data.get("mods_id")
        if mods_id is None:
            raise ValueError("Missing 'mods_id' in data.")

        identity_data: dict|None = data.get("identity")
        if identity_data is None:
            raise ValueError("Missing 'identity' in data.")

        identity: PeopleGatorIdentity = PeopleGatorIdentity.from_dict(identity_data)

        name: str|None = data.get("name")
        if name is None:
            raise ValueError("Missing 'name' in data.")

        peoplegator_id: str|None = data.get("peoplegator_id")
        if peoplegator_id is None:
            raise ValueError("Missing 'peoplegator_id' in data.")

        return cls(tag_id=tag_id,
                   mods_id=mods_id,
                   mods_uuid=data.get("mods_uuid"),
                   record_identifier=data.get("record_identifier"),
                   used_ai_models=data.get("used_ai_models"),
                   creation_date_time=data.get("creation_date_time"),
                   confidence=data.get("confidence"),
                   identity=identity)


class PeopleGatorFaceMetadata(AnnoPageBaseMetadata):
    def __init__(self,
                 tag_id: str,
                 mods_id: str,
                 page_identity: PeopleGatorPageIdentity,
                 left_eye_position: Position,
                 right_eye_position: Position,
                 nose_position: Position,
                 left_mouth_corner_position: Position,
                 right_mouth_corner_position: Position,
                 mods_uuid: str|None = None,
                 record_identifier: str|None = None,
                 used_ai_models: dict|None = None,
                 creation_date_time=None,
                 confidence: float|None = None):
        super().__init__(tag_id,
                         mods_id,
                         mods_uuid,
                         record_identifier,
                         used_ai_models,
                         creation_date_time,
                         confidence)

        self.page_identity: PeopleGatorPageIdentity = page_identity

        self.left_eye_position: Position = left_eye_position
        self.right_eye_position: Position = right_eye_position
        self.nose_position: Position = nose_position
        self.left_mouth_corner_position: Position = left_mouth_corner_position
        self.right_mouth_corner_position: Position = right_mouth_corner_position

    def __repr__(self):
        return f"PeopleGatorFaceMetadata(tag_id={self.tag_id}, mods_id={self.mods_id}, page_identity={repr(self.page_identity)}, left_eye_position={repr(self.left_eye_position)}, right_eye_position={repr(self.right_eye_position)}, nose_position={repr(self.nose_position)}, left_mouth_corner_position={repr(self.left_mouth_corner_position)}, right_mouth_corner_position={repr(self.right_mouth_corner_position)})"

    @property
    def identity_name(self):
        return self.page_identity.identity.name

    def to_dict(self):
        result = super().to_dict()

        result.update({
            "left_eye_position": self.left_eye_position.to_json() if self.left_eye_position is not None else None,
            "right_eye_position": self.right_eye_position.to_json() if self.right_eye_position is not None else None,
            "nose_position": self.nose_position.to_json() if self.nose_position is not None else None,
            "left_mouth_corner_position": self.left_mouth_corner_position.to_json() if self.left_mouth_corner_position is not None else None,
            "right_mouth_corner_position": self.right_mouth_corner_position.to_json() if self.right_mouth_corner_position is not None else None,
            "page_identity": self.page_identity.to_dict() if self.page_identity is not None else None
        })

        return result

    @classmethod
    def from_dict(cls, data: dict):
        page_identity = PeopleGatorPageIdentity.from_dict(data["page_identity"])

        left_eye_position = Position.from_json(data["left_eye_position"])
        right_eye_position = Position.from_json(data["right_eye_position"])
        nose_position = Position.from_json(data["nose_position"])
        left_mouth_corner_position = Position.from_json(data["left_mouth_corner_position"])
        right_mouth_corner_position = Position.from_json(data["right_mouth_corner_position"])

        return cls(tag_id=data["tag_id"],
                   mods_id=data["mods_id"],
                   page_identity=page_identity,
                   left_eye_position=left_eye_position,
                   right_eye_position=right_eye_position,
                   nose_position=nose_position,
                   left_mouth_corner_position=left_mouth_corner_position,
                   right_mouth_corner_position=right_mouth_corner_position,
                   mods_uuid=data.get("mods_uuid", None),
                   record_identifier=data.get("record_identifier", None),
                   used_ai_models=data.get("used_ai_models", None),
                   creation_date_time=data.get("creation_date_time", None),
                   confidence=data.get("confidence", None))

    def to_altoxml(self, print_space, bounding_box, source_region=None):
        tags = find_or_create_tags_element(print_space)
        self.to_altoxml_layout(tags, bounding_box, source_region)
        self.to_altoxml_identity(tags)

    def to_altoxml_layout(self, tags, bounding_box, source_region=None):
        layout_tag = ET.SubElement(tags, "LayoutTag")
        xml_data = ET.SubElement(layout_tag, "XmlData")

        layout_tag.set("ID", self.tag_id)
        layout_tag.set("TYPE", "Structural")
        layout_tag.set("LABEL", "face")

        mods_namespace = globals.mods_xml_namespace
        mods_xmlns = {globals.mods_xml_prefix: mods_namespace}
        mods = ET.SubElement(xml_data, f"{{{mods_namespace}}}mods", nsmap=mods_xmlns)

        mods.set("ID", self.mods_id)

        self._add_size_element(mods, mods_namespace, bounding_box)
        self._add_type_of_resource_element(mods, mods_namespace, "person faces")

        self._add_genre_element(mods, mods_namespace, language=None, content="face")
        self._add_genre_element(mods, mods_namespace, str(Language.ENGLISH), content="face")
        self._add_genre_element(mods, mods_namespace, str(Language.CZECH), content="obličej")

        if self.page_identity is not None:
            self._add_related_item_element(mods, mods_namespace, item_type=None, item_other_type="info", item_id=self.page_identity.mods_id)

        if source_region is not None and source_region.graphical_metadata is not None:
            self._add_related_item_element(mods, mods_namespace, item_type="host", item_id=source_region.graphical_metadata.mods_id)

        self._add_identifier_element(mods, mods_namespace, self.mods_uuid)

        if self.creation_date_time is not None:
            creation_date_time = self.creation_date_time
        else:
            creation_date_time = DateTimeService.get_datetime_now().isoformat(timespec='seconds')

        self._add_record_info_element(mods,
                                      mods_namespace,
                                      content_source=globals.software_name,
                                      creation_date_time=creation_date_time,
                                      record_identifier=self.record_identifier,
                                      confidence=self.confidence,
                                      used_ai_models=self.used_ai_models)

        peoplegator_namespace = globals.peoplegator_xml_namespace
        pg_xmlns = {globals.peoplegator_xml_prefix: peoplegator_namespace}

        peoplegator = ET.SubElement(xml_data, f"{{{peoplegator_namespace}}}peoplegator", nsmap=pg_xmlns)
        key_points = ET.SubElement(peoplegator, f"{{{peoplegator_namespace}}}key-points")

        self._add_point(key_points, peoplegator_namespace, "left-eye", self.left_eye_position)
        self._add_point(key_points, peoplegator_namespace, "right-eye", self.right_eye_position)
        self._add_point(key_points, peoplegator_namespace, "nose", self.nose_position)
        self._add_point(key_points, peoplegator_namespace, "left-mouth-corner", self.left_mouth_corner_position)
        self._add_point(key_points, peoplegator_namespace, "right-mouth-corner", self.right_mouth_corner_position)

    def to_altoxml_identity(self, tags):
        namespaces = tags.nsmap

        ns = {
            "alto": namespaces[None],
            globals.mods_xml_prefix: globals.mods_xml_namespace
        }

        named_entity_tag = tags.xpath(f"./alto:NamedEntityTag[alto:XmlData/mods:mods[@ID='{self.page_identity.mods_id}']]", namespaces=ns)
        if not named_entity_tag:
            self.page_identity.to_altoxml(tags)

    @staticmethod
    def _add_size_element(mods, mods_namespace, bounding_box):
        x_min, y_min, x_max, y_max = bounding_box
        width = round(x_max - x_min)
        height = round(y_max - y_min)

        physical_description = ET.SubElement(mods, f"{{{mods_namespace}}}physicalDescription")
        extent = ET.SubElement(physical_description, f"{{{mods_namespace}}}extent")
        extent.text = f"{width}x{height}"
        extent.attrib["unit"] = "pixels"

    @staticmethod
    def _add_point(parent, peoplegator_namespace:str, key: str, position: Position, unit: str = "pixels"):
        point = ET.SubElement(parent, f"{{{peoplegator_namespace}}}points")
        point.attrib["key"] = key
        point.attrib["x"] = f"{position.x:.2f}"
        point.attrib["y"] = f"{position.y:.2f}"
        point.attrib["unit"] = unit

    @staticmethod
    def _add_namespace(element, prefix: str, uri: str):
        root_element = get_root_element(element)
        if prefix not in root_element.nsmap:
            nsmap = dict(root_element.nsmap)
            nsmap[prefix] = uri
            root_element.nsmap = nsmap

        namespace = root_element.nsmap[prefix]

        return namespace

    @classmethod
    def from_altoxml(cls):
        raise NotImplementedError("Not implemented yet.")


class PeopleGatorFaceRegionLayout(RegionLayout):
    def __init__(self,
                 id: str,
                 polygon: np.ndarray,
                 face_metadata: PeopleGatorFaceMetadata,
                 source_region: RegionLayout|None,
                 region_type: str|None = None,
                 category: str|None = None,
                 detection_confidence: float|None = None):
        super().__init__(id=id,
                         polygon=polygon,
                         region_type=region_type,
                         category=category,
                         detection_confidence=detection_confidence)

        self.face_metadata: PeopleGatorFaceMetadata = face_metadata
        self.source_region: RegionLayout|None = source_region

    def __repr__(self):
        return f"PeopleGatorFaceRegionLayout(id={self.id}, polygon={self.polygon.tolist()}, region_type={self.region_type}, category={self.category}, detection_confidence={self.detection_confidence}, source_region_id={self.source_region.id if self.source_region else None}, face_metadata={repr(self.face_metadata)})"

    def to_altoxml(self, print_space, arabic_helper, min_line_confidence,
                   print_space_coords: Tuple[int, int, int, int], version: ALTOVersion, word_splitters=["-"]) -> Tuple[int, int, int, int]:
        page_element = get_page_element(print_space)
        page_id = page_element.attrib["ID"]

        composed_block_id = get_next_id(print_space, "ComposedBlock", prefix=f"{page_id}_CB", padding=4)
        composed_block_element = ET.SubElement(print_space, "ComposedBlock")
        composed_block_element.set("ID", composed_block_id)
        composed_block_element.set("TYPE", "Face")

        graphical_element_id = get_next_id(print_space, "GraphicalElement", prefix=f"{page_id}_GE", padding=4)
        graphical_element = ET.SubElement(composed_block_element, "GraphicalElement")
        graphical_element.set("ID", graphical_element_id)

        bounding_box = self.get_polygon_bounding_box()
        set_position_and_size(composed_block_element, bounding_box)
        set_position_and_size(graphical_element, bounding_box)

        x_min, y_min, x_max, y_max = bounding_box
        block_height, block_width, block_vpos, block_hpos = y_max - y_min, x_max - x_min, y_min, x_min
        print_space_height, print_space_width, print_space_vpos, print_space_hpos = print_space_coords

        print_space_height = max([print_space_vpos + print_space_height, block_vpos + block_height])
        print_space_width = max([print_space_hpos + print_space_width, block_hpos + block_width])
        print_space_vpos = min([print_space_vpos, block_vpos])
        print_space_hpos = min([print_space_hpos, block_hpos])
        print_space_height = print_space_height - print_space_vpos
        print_space_width = print_space_width - print_space_hpos

        if self.face_metadata is not None:
            self.face_metadata.to_altoxml(print_space,
                                          bounding_box=bounding_box,
                                          source_region=self.source_region)

            composed_block_element.set("TAGREFS", self.face_metadata.tag_id)

        return print_space_height, print_space_width, print_space_vpos, print_space_hpos


    @classmethod
    def from_altoxml(cls, text_block, schema, generated_block_id=None):
        raise NotImplementedError("Not implemented yet.")

    def to_pagexml(self, page_element, validate_id: bool = False):
        custom = {
            "category": self.category,
            "detection_confidence": round(self.detection_confidence, 3) if self.detection_confidence is not None else None,
            "metadata": self.face_metadata.to_dict() if self.face_metadata is not None else None,
            "source_region": self.source_region.id if self.source_region is not None else None
        }

        region_element = ET.SubElement(page_element, "ImageRegion")
        region_element.attrib["id"] = self.id
        region_element.attrib["custom"] = json.dumps(custom)

        if self.region_type is not None:
            region_element.attrib["type"] = self.region_type

        coords = ET.SubElement(region_element, "Coords")
        coords.attrib["points"] = " ".join([f"{int(x)},{int(y)}" for x, y in self.polygon])

    @classmethod
    def from_pagexml(cls, region_element, schema, page_layout=None):
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

        custom = json.loads(region_element.attrib["custom"])
        category = custom.get("category", None)
        detection_confidence = custom.get("detection_confidence", None)
        source_region_id = custom.get("source_region", None)

        source_region = None
        if source_region_id is not None and page_layout is not None:
            for region in page_layout.regions:
                if region.id == source_region_id:
                    source_region = region
                    break

        face_metadata = PeopleGatorFaceMetadata.from_dict(custom["metadata"])

        region = cls(region_id,
                     polygon=polygon,
                     region_type=region_type,
                     category=category,
                     detection_confidence=detection_confidence,
                     source_region=source_region,
                     face_metadata=face_metadata)

        return region

    @classmethod
    def from_app_dict(cls, db_face, db_entity, page_layout):
        region_id = db_face["identifier"]
        bounding_box = db_face["bounding_box"]
        confidence = db_face["confidence"]

        x = bounding_box["x"]
        y = bounding_box["y"]
        width = bounding_box["width"]
        height = bounding_box["height"]

        polygon = np.array([[x, y],
                            [x + width, y],
                            [x + width, y + height],
                            [x, y + height],
                            [x, y]])

        left_eye = Position.from_json([keypoint for keypoint in db_face["keypoints"] if keypoint["type"] == "left_eye"][0])
        right_eye = Position.from_json([keypoint for keypoint in db_face["keypoints"] if keypoint["type"] == "right_eye"][0])
        nose = Position.from_json([keypoint for keypoint in db_face["keypoints"] if keypoint["type"] == "nose"][0])
        left_mouth_corner = Position.from_json([keypoint for keypoint in db_face["keypoints"] if keypoint["type"] == "left_mouth_corner"][0])
        right_mouth_corner = Position.from_json([keypoint for keypoint in db_face["keypoints"] if keypoint["type"] == "right_mouth_corner"][0])

        source_region = find_source_region_by_bounding_box(page_layout, (x, y, x + width, y + height))

        identity_name = None
        peoplegator_id = None

        if db_entity is not None:
            identity_name = db_entity.get("name")
            peoplegator_id = db_entity.get("entity_id")

        identity = PeopleGatorIdentity(name=identity_name, peoplegator_id=peoplegator_id)

        person_region_id = get_next_region_id(page_layout, prefix="person")
        page_identity = PeopleGatorPageIdentity(tag_id=person_region_id,
                                                mods_id=get_next_mods_id(page_layout, prefix="MODS_PERSON"),
                                                identity=identity)

        face_metadata = PeopleGatorFaceMetadata(tag_id=region_id,
                                                mods_id=get_next_mods_id(page_layout, prefix="MODS_FACE"),
                                                page_identity=page_identity,
                                                left_eye_position=left_eye,
                                                right_eye_position=right_eye,
                                                nose_position=nose,
                                                left_mouth_corner_position=left_mouth_corner,
                                                right_mouth_corner_position=right_mouth_corner,)

        region = cls(id=region_id,
                     polygon=polygon,
                     face_metadata=face_metadata,
                     source_region=source_region,
                     category="face",
                     detection_confidence=confidence)

        return region


class PeopleGatorTextEntityMention:
    def __init__(self,
                 name: str,
                 text: str,
                 line: TextLine,
                 span: tuple[int, int],
                 page_identity: PeopleGatorPageIdentity):
        self.name: str = name
        self.text: str = text
        self.line: TextLine = line
        self.span: tuple[int, int] = span
        self.page_identity: PeopleGatorPageIdentity = page_identity

    @property
    def identity_name(self):
        return self.page_identity.identity.name

    def __repr__(self):
        return f"PeopleGatorTextEntityMention(name={self.name}, text={self.text}, line_id={self.line.id}, span={self.span}, identity={repr(self.page_identity) if self.page_identity else None})"


class PeopleGatorPageLayout(AnnoPagePageLayout):
    def __init__(self, id: str|None = None, page_size: tuple[int, int] = (0, 0), file: str|None = None):
        super().__init__(id, page_size, file)

        self.text_entities: list[PeopleGatorTextEntityMention] = []

        self.from_altoxml_ended += altoxml_load_regions
        self.from_pagexml_ended += pagexml_load_regions

        self.to_altoxml_processing_added += altoxml_add_processing_step
        self.to_altoxml_regions_ended += altoxml_postprocess_lines
        self.to_pagexml_processing_added += pagexml_add_processing_step

    @property
    def faces(self):
        return [region for region in self.regions if isinstance(region, PeopleGatorFaceRegionLayout)]

    def to_app_dict(self):
        regions = []
        for region in self.regions:
            if region.category not in {'text', None}:
                continue

            lines = []
            for line in region.lines:
                line_data = {
                    "id": line.id,
                    "polygon": line.polygon.tolist(),
                    "heights": line.heights.tolist(),
                    "baseline": line.baseline.tolist(),
                    "transcription": line.transcription,
                    "transcription_confidence": 1
                }

                lines.append(line_data)

            region_data = {
                "id": region.id,
                "polygon": region.polygon,
                "transcription": "",
                "lines": lines
            }

            regions.append(region_data)

        data = {
            "id": self.id,
            "page_size": [self.page_size[0], self.page_size[1]],
            "regions": regions,
            "reading_order": {}
        }

        return data


class PeopleGatorTextEntityCluster:
    def __init__(self,
                 text_entities: list[PeopleGatorTextEntityMention],
                 identity: PeopleGatorIdentity,
                 name: str|None = None,
                 description: str|None = None):
        self.text_entities: list[PeopleGatorTextEntityMention] = text_entities
        self.identity: PeopleGatorIdentity = identity
        self.name: str|None = name
        self.description: str|None = description

    def __repr__(self):
        return f"PeopleGatorTextEntityCluster(name={self.name}, identity_id={self.identity.peoplegator_id if self.identity else None}, num_entities={len(self.text_entities)})"


class PeopleGatorDocument:

    def __init__(self,
                 id: str|None = None,
                 name: str|None = None,
                 library: str|None = None,
                 page_layouts: list[PeopleGatorPageLayout]|None = None,
                 page_xmls_dir: str|None = None,
                 alto_xmls_dir: str|None = None,
                 metadata_path: str|None = None,
                 text_entity_clusters: list[PeopleGatorTextEntityCluster]|None = None,
                 page_images: dict[str, np.ndarray]|None = None,
                 page_images_dir: str|None = None,
                 load_images: bool = False,
                 keep_images_in_memory: bool = False):
        self.id = id
        self.name = name
        self.library = library

        self.page_layouts: list[PeopleGatorPageLayout] = page_layouts if page_layouts is not None else []
        self.page_xmls_dir: str|None = page_xmls_dir
        self.alto_xmls_dir: str|None = alto_xmls_dir
        self.metadata_path: str|None = metadata_path

        self.text_entity_clusters: list[PeopleGatorTextEntityCluster] = text_entity_clusters if text_entity_clusters is not None else []

        self.page_images = page_images if page_images is not None else {}
        self.page_images_dir: str|None = page_images_dir

        self.load_images: bool = load_images
        self.keep_images_in_memory: bool = keep_images_in_memory

        if not self.page_layouts:
            if self.page_xmls_dir and self.alto_xmls_dir:
                raise ValueError("Cannot specify both page_xmls_dir and alto_xmls_dir.")

            if self.page_xmls_dir:
                self.from_pagexml(self.page_xmls_dir)

            elif self.alto_xmls_dir:
                self.from_altoxml(self.alto_xmls_dir)

        if self.load_images:
            self.load_page_images()

        if self.metadata_path:
            self.load_metadata()

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

    def load_metadata(self):
        if self.metadata_path:
            with open(self.metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            self.id = metadata["document"]["id"] if "document" in metadata and "id" in metadata["document"] else None
            self.name = metadata["document"]["name"] if "document" in metadata and "name" in metadata["document"] else None
            self.library = metadata["document"]["library"] if "document" in metadata and "library" in metadata["document"] else None

            pages_metadata = metadata.get("pages_metadata", {})
            for page_layout in self.page_layouts:
                if page_layout.id in pages_metadata:
                    page_layout.metadata["people_gator_metadata"] = pages_metadata[page_layout.id]

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
            page_layout = PeopleGatorPageLayout()
            page_layout.from_altoxml(file_path)
            page_layouts.append(page_layout)

        self.page_layouts = page_layouts
        self.build_text_entity_clusters()

    def to_altoxml(self, output_dir, alto_version=ALTOVersion.ALTO_v4_4):
        if self.page_layouts:
            self.distribute_text_entity_identities()
            parser = ET.XMLParser(remove_blank_text=True)

            for page_layout in self.page_layouts:
                output_path = os.path.join(output_dir, f"{page_layout.id}.xml")

                if self.alto_xmls_dir is not None:
                    input_path = os.path.join(self.alto_xmls_dir, f"{page_layout.id}.xml")

                    tree = ET.parse(input_path, parser)
                    alto = tree.getroot()

                    alto = remove_peoplegator_elements(alto)
                    alto = add_page_layout_to_alto(page_layout, alto)

                    with open(output_path, 'w', encoding="utf-8") as file:
                        file.write(ET.tostring(alto, pretty_print=True, encoding="utf-8", xml_declaration=True).decode("utf-8"))
                else:
                    page_layout.to_altoxml(output_path)

    def from_pagexml(self, pagexml_dir: str):
        files = [file for file in os.listdir(pagexml_dir) if file.lower().endswith('.xml')]
        page_layouts = []

        for file in files:
            file_path = os.path.join(pagexml_dir, file)
            page_layout = PeopleGatorPageLayout(file=file_path)
            page_layouts.append(page_layout)

        self.page_layouts = page_layouts
        self.build_text_entity_clusters()

    def to_pagexml(self, output_dir):
        if self.page_layouts:
            self.distribute_text_entity_identities()
            for page_layout in self.page_layouts:
                output_path = os.path.join(output_dir, f"{page_layout.id}.xml")
                page_layout.to_pagexml(output_path)

    def build_text_entity_clusters(self, drop_mentions_identities=False, create_clusters_without_identity=False):
        clusters = []
        identity_to_cluster = {}
        for page_layout in self.page_layouts:
            for text_entity in page_layout.text_entities:
                identity_id = text_entity.page_identity.identity.peoplegator_id
                if identity_id is None and not create_clusters_without_identity:
                    continue

                if identity_id in identity_to_cluster:
                    cluster = identity_to_cluster[identity_id]
                    cluster.text_entities.append(text_entity)
                else:
                    cluster = PeopleGatorTextEntityCluster(text_entities=[text_entity], identity=text_entity.page_identity.identity)
                    clusters.append(cluster)
                    identity_to_cluster[identity_id] = cluster

                if drop_mentions_identities:
                    text_entity.page_identity.identity = None

        self.text_entity_clusters = clusters

    def distribute_text_entity_identities(self):
        for cluster in self.text_entity_clusters:
            for text_entity in cluster.text_entities:
                text_entity.page_identity.identity = cluster.identity


def remove_peoplegator_elements(alto_root):
    return alto_root


def add_page_layout_to_alto(page_layout: AnnoPagePageLayout, alto_root, alto_version=ALTOVersion.ALTO_v4_4):
    description_element = find_or_create_element(alto_root, "Description")
    tags_element = find_or_create_element(alto_root, "Tags")
    layout_element = find_or_create_element(alto_root, "Layout")
    page_element = find_or_create_element(layout_element, "Page")
    print_space_element = find_or_create_element(page_element, "PrintSpace")

    altoxml_add_processing_step(page_layout, description_element, alto_version)

    print_space_coords = get_print_space_coords(page_layout, print_space_element)

    for region in page_layout.regions:
        if isinstance(region, PeopleGatorFaceRegionLayout):
            print_space_coords = region.to_altoxml(print_space_element, None, 0.0, print_space_coords, alto_version)

    update_print_space_and_margins(page_layout, page_element, print_space_coords)

    altoxml_postprocess_lines(page_layout, print_space_element, alto_version)

    return alto_root


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


def pagexml_add_processing_step(page_layout, metadata):
    metadata_item = ET.SubElement(metadata, "MetadataItem")
    metadata_item.set("type", "processingStep")
    metadata_item.set("name", "Face detection and analysis and named entity recognition")
    metadata_item.set("value", globals.software_fullname)
    metadata_item.set("date", DateTimeService.get_datetime_now().isoformat())


def altoxml_postprocess_lines(page_layout, print_space_element, alto_version=ALTOVersion.ALTO_v4_4):
    pass


def get_next_mods_id(page_layout, prefix="MODS_FACE", padding=4):
    regions = [region for region in page_layout.regions if isinstance(region, PeopleGatorFaceRegionLayout)]
    existing_mods_ids = set([region.face_metadata.mods_id for region in regions if region.face_metadata and region.face_metadata.mods_id])

    index = 1
    new_id = f"{prefix}_{str(index).zfill(padding)}"

    while new_id in existing_mods_ids:
        index += 1
        new_id = f"{prefix}_{str(index).zfill(padding)}"

    return new_id


def get_next_region_id(page_layout, prefix, padding=3):
    existing_region_ids = set([region.id for region in page_layout.regions])

    index = 1
    new_id = f"{prefix}_{str(index).zfill(padding)}"

    while new_id in existing_region_ids:
        index += 1
        new_id = f"{prefix}_{str(index).zfill(padding)}"

    return new_id


def render_to_image(image, page_layout):
    render = np.copy(image)

    for region in page_layout.regions:
        if isinstance(region, PeopleGatorFaceRegionLayout):
            x_min, y_min, x_max, y_max = region.get_polygon_bounding_box()
            cv2.rectangle(render, (round(x_min), round(y_min)), (round(x_max), round(y_max)), (255, 0, 0), 3)

            name = None
            if region.face_metadata:
                name = region.face_metadata.identity_name

            if name is not None:
                cv2.putText(render, name, (round(x_min), round(y_min) - 10), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 0, 0), 1)

            if region.face_metadata:
                for position, color in [(region.face_metadata.left_eye_position, (75, 180, 60)),
                                        (region.face_metadata.right_eye_position, (200, 130, 0)),
                                        (region.face_metadata.nose_position, (48, 130, 245)),
                                        (region.face_metadata.left_mouth_corner_position, (75, 25, 230)),
                                        (region.face_metadata.right_mouth_corner_position, (230, 50, 240))]:
                    if position is not None:
                        cv2.circle(render, (round(position.x), round(position.y)), radius=3, color=color, thickness=-1)

    return render
