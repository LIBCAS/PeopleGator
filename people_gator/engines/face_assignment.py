import cv2
import logging
import numpy as np

from pydantic import BaseModel, ConfigDict
from collections import defaultdict

from anno_page.core.layout import AnnoPageRegionLayout
from anno_page.enums.language import Language

from people_gator.core.utils import find_text_in_bounding_box
from people_gator.core.layout import PeopleGatorFaceRegionLayout, PeopleGatorPageIdentity, PeopleGatorIdentity
from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine


logger = logging.getLogger(__name__)


class FaceIdentifier(BaseModel):
    id: str
    coordinates: tuple[int, int, int, int]


class FaceAssignmentData:
    def __init__(self, face_region, face_image, face_coordinates, context_image, context_text=None, caption_text=None, result=None):
        self.face_region = face_region
        self.face_image = face_image
        self.face_coordinates = face_coordinates
        self.context_image = context_image
        self.context_text = context_text
        self.caption_text = caption_text
        self.result = result

    def __repr__(self):
        return f"FaceAssignmentData(face_region={self.face_region}, face_image={self.face_image}, context_image={self.context_image}, context_text={self.context_text}, caption_text={self.caption_text}, result={repr(self.result)})"


class FaceAssignmentResult(BaseModel):
    name_normalized: str|None
    name_in_text: str|None

    def __repr__(self):
        return f"FaceAssignmentResult(name_normalized={self.name_normalized}, name_in_text={self.name_in_text})"


class LLMFaceAssignmentEngine(DocumentProcessingEngine, LLMBasedEngine):
    def __init__(self, config, device, config_path):
        super().__init__(config, device, config_path)

        self.vertical_offset = self.config.getint("vertical_offset", 0)
        self.horizontal_offset = self.config.getint("horizontal_offset", 0)

    def process_document(self, document):
        for page_image, page_layout in document.pages_iterator():
            self.process_page(page_image, page_layout)

        return document

    def process_page(self, page_image, page_layout):
        face_data = self.prepare_face_data(page_image, page_layout)

        for face_item in face_data:
            result, messages = self.llm_prompter(data={
                                                     "face_coordinates": face_item.face_coordinates,
                                                     "context_text": face_item.context_text,
                                                     "caption_text": face_item.caption_text
                                                 },
                                                 images=[face_item.face_image, face_item.context_image],
                                                 response_model=FaceAssignmentResult)
            face_item.result = result

        page_layout = self.update_layout(page_layout, face_data)

        return page_layout

    def prepare_face_data(self, page_image, page_layout) -> list[FaceAssignmentData]:
        face_data = []
        for i, region in enumerate(page_layout.regions):
            if isinstance(region, PeopleGatorFaceRegionLayout):
                face_x_min, face_y_min, face_x_max, face_y_max = region.get_polygon_bounding_box()
                face_image = page_image[face_y_min:face_y_max, face_x_min:face_x_max]

                source_region = region.source_region

                median_line_height = np.median([line.heights[0] + line.heights[1] for line in page_layout.lines_iterator()])
                vertical_offset = int(median_line_height * self.vertical_offset)
                horizontal_offset = int(median_line_height * self.horizontal_offset)

                source_x_min, source_y_min, source_x_max, source_y_max = source_region.get_polygon_bounding_box()
                context_x_min = max(0, source_x_min - horizontal_offset)
                context_y_min = max(0, source_y_min - vertical_offset)
                context_x_max = min(page_image.shape[1], source_x_max + horizontal_offset)
                context_y_max = min(page_image.shape[0], source_y_max + vertical_offset)

                context_image = np.copy(page_image[context_y_min:context_y_max, context_x_min:context_x_max])

                face_relative_x_min = face_x_min - context_x_min
                face_relative_y_min = face_y_min - context_y_min
                face_relative_x_max = face_x_max - context_x_min
                face_relative_y_max = face_y_max - context_y_min

                cv2.rectangle(context_image, (face_relative_x_min, face_relative_y_min), (face_relative_x_max, face_relative_y_max), (0, 255, 0), 3)

                face_center_x = (face_x_min + face_x_max) / 2
                face_center_y = (face_y_min + face_y_max) / 2

                face_center_x_relative = round(100 * (face_center_x - context_x_min) / (context_x_max - context_x_min))
                face_center_y_relative = round(100 * (face_center_y - context_y_min) / (context_y_max - context_y_min))

                face_coordinates = (face_center_x_relative, face_center_y_relative)

                context_bbox = (context_x_min, context_y_min, context_x_max, context_y_max)
                context_text = find_text_in_bounding_box(page_layout, context_bbox)

                caption_text = None
                if isinstance(source_region, AnnoPageRegionLayout) and source_region.graphical_metadata is not None:
                    caption_text = source_region.graphical_metadata.title

                face_item = FaceAssignmentData(face_region=region,
                                               face_image=face_image,
                                               face_coordinates=face_coordinates,
                                               context_image=context_image,
                                               context_text=context_text,
                                               caption_text=caption_text)

                face_data.append(face_item)

        return face_data

    def update_layout(self, page_layout, face_data: list[FaceAssignmentData]):
        for face_item in face_data:
            face_region = face_item.face_region
            if face_item.result is not None:
                if face_region.face_metadata is None:
                    logger.warning(f"Face region {face_region.id} has no face metadata, skipping update.")
                    continue

                face_region.face_metadata.page_identity.identity.name = face_item.result.name_normalized

        return page_layout

    @staticmethod
    def get_next_mods_id(page_layout, prefix="MODS_PERSON", padding=4):
        regions = [region for region in page_layout.regions if isinstance(region, PeopleGatorFaceRegionLayout)]
        existing_mods_ids = set([region.face_metadata.page_identity.mods_id for region in regions
                                 if region.face_metadata is not None
                                 and region.face_metadata.page_identity is not None
                                 and region.face_metadata.page_identity.mods_id is not None])

        index = 1
        new_id = f"{prefix}_{str(index).zfill(padding)}"

        while new_id in existing_mods_ids:
            index += 1
            new_id = f"{prefix}_{str(index).zfill(padding)}"

        return new_id


class BatchFaceAssignmentResultItem(BaseModel):
    id: int
    coordinates: list[int]
    name_in_text: str|None
    name_normalized: str|None

    model_config = ConfigDict(extra="forbid")


class BatchFaceAssignmentResult(BaseModel):
    faces: list[BatchFaceAssignmentResultItem]


class BatchFaceAssignmentData:
    def __init__(self, context_text=None, caption_text=None, context_image=None, faces=None, face_regions=None, result=None):
        self.context_text = context_text
        self.caption_text = caption_text
        self.context_image = context_image
        self.faces = faces
        self.face_regions = face_regions
        self.result = result

    def __repr__(self):
        return f"BatchFaceAssignmentData(context_text={self.context_text}, caption_text={self.caption_text}, context_image={self.context_image}, faces={self.faces}, face_regions={self.face_regions}, result={self.result})"


class LLMBatchFaceAssignmentEngine(DocumentProcessingEngine, LLMBasedEngine):
    def __init__(self, config, device, config_path):
        super().__init__(config, device, config_path)

        self.max_people = self.config.getint("max_people", 3)
        self.colors = {
            "red": (255, 0, 0),
            "green": (0, 255, 0),
            "blue": (0, 0, 255),
            "yellow": (255, 255, 0),
            "magenta": (255, 0, 255),
            "cyan": (0, 255, 255)
        }

        self.vertical_offset = self.config.getint("vertical_offset", 0)
        self.horizontal_offset = self.config.getint("horizontal_offset", 0)

    def process_document(self, document):
        for page_image, page_layout in document.pages_iterator():
            self.process_page(page_image, page_layout)

        return document

    def process_page(self, page_image, page_layout):
        face_data = self.prepare_face_data(page_image, page_layout)
        for face_item in face_data:
            result, messages = self.llm_prompter(data={
                                                     "faces": face_item.faces,
                                                     "context_text": face_item.context_text,
                                                     "caption_text": face_item.caption_text
                                                 },
                                                 images=[face_item.context_image],
                                                 response_model=BatchFaceAssignmentResult)
            face_item.result = result

        page_layout = self.update_layout(page_layout, face_data)

        return page_layout

    def prepare_face_data(self, page_image, page_layout) -> list[BatchFaceAssignmentData]:
        face_data = []

        source_regions_mapping = defaultdict(list)
        for i, region in enumerate(page_layout.regions):
            if isinstance(region, PeopleGatorFaceRegionLayout):
                source_regions_mapping[region.source_region].append(region)

        median_line_height = np.median([line.heights[0] + line.heights[1] for line in page_layout.lines_iterator()])
        vertical_offset = int(median_line_height * self.vertical_offset)
        horizontal_offset = int(median_line_height * self.horizontal_offset)

        for source_region, face_regions in source_regions_mapping.items():
            if len(face_regions) > self.max_people:
                logger.info(f"Found {len(face_regions)} face regions for source region {source_region.id}, which exceeds the maximum of {self.max_people}. Skipping this source region.")
                continue

            source_x_min, source_y_min, source_x_max, source_y_max = source_region.get_polygon_bounding_box()
            context_x_min = max(0, source_x_min - horizontal_offset)
            context_y_min = max(0, source_y_min - vertical_offset)
            context_x_max = min(page_image.shape[1], source_x_max + horizontal_offset)
            context_y_max = min(page_image.shape[0], source_y_max + vertical_offset)

            context_bbox = (context_x_min, context_y_min, context_x_max, context_y_max)
            context_text = find_text_in_bounding_box(page_layout, context_bbox)

            context_image = np.copy(page_image[context_y_min:context_y_max, context_x_min:context_x_max])

            sorted_face_regions = sorted(face_regions, key=lambda r: r.get_polygon_bounding_box()[0] + (r.get_polygon_bounding_box()[0] + r.get_polygon_bounding_box()[2]) / 2)
            faces = []
            for i, face_region in enumerate(sorted_face_regions):
                face_color_name = list(self.colors.keys())[i % len(self.colors)]
                face_color = self.colors[face_color_name]

                face_x_min, face_y_min, face_x_max, face_y_max = face_region.get_polygon_bounding_box()
                face_relative_x_min = face_x_min - context_x_min
                face_relative_y_min = face_y_min - context_y_min
                face_relative_x_max = face_x_max - context_x_min
                face_relative_y_max = face_y_max - context_y_min

                cv2.rectangle(context_image, (face_relative_x_min, face_relative_y_min), (face_relative_x_max, face_relative_y_max), face_color[::-1], 3)

                face_width = face_x_max - face_x_min
                face_height = face_y_max - face_y_min

                face_center_x = face_x_min + face_width / 2
                face_center_y = face_y_min + face_height / 2

                face_center_x_relative = round(100 * (face_center_x - context_x_min) / (context_x_max - context_x_min))
                face_center_y_relative = round(100 * (face_center_y - context_y_min) / (context_y_max - context_y_min))

                face_coordinates = (face_center_x_relative, face_center_y_relative)

                faces.append(
                    {
                        "id": i,
                        "coordinates": face_coordinates,
                        "color": face_color,
                        "color_name": face_color_name
                    }
                )

            caption_text = None
            if isinstance(source_region, AnnoPageRegionLayout) and source_region.graphical_metadata is not None:
                caption_text = source_region.graphical_metadata.title

                if isinstance(caption_text, dict):
                    if Language.CZECH in caption_text:
                        caption_text = caption_text[Language.CZECH]
                    elif Language.ENGLISH in caption_text:
                        caption_text = caption_text[Language.ENGLISH]
                    else:
                        caption_text = next(iter(caption_text.values()), None)

            face_item = BatchFaceAssignmentData(
                context_text=context_text,
                caption_text=caption_text,
                context_image=context_image,
                faces=faces,
                face_regions=sorted_face_regions,
                result=None
            )

            face_data.append(face_item)

        return face_data

    def update_layout(self, page_layout, face_data: list[BatchFaceAssignmentData]):
        for face_item in face_data:
            if face_item.result is not None:
                for face_result in face_item.result.faces:
                    target_face_region = None
                    for face, face_region in zip(face_item.faces, face_item.face_regions):
                        if face["id"] == face_result.id and all([coord1 == coord2 for coord1, coord2 in zip(face["coordinates"], face_result.coordinates)]):
                            target_face_region = face_region
                            break

                    if target_face_region is None:
                        logger.warning(f"No matching face region found for face result {face_result.id} with coordinates {face_result.coordinates}. Skipping update.")
                        continue

                    if target_face_region.face_metadata is None:
                        logger.warning(f"Face region {target_face_region.id} has no face metadata, skipping update.")
                        continue

                    target_face_region.face_metadata.page_identity.identity.name = face_result.name_normalized

        return page_layout

    @staticmethod
    def get_next_mods_id(page_layout, prefix="MODS_PERSON", padding=4):
        regions = [region for region in page_layout.regions if isinstance(region, PeopleGatorFaceRegionLayout)]
        existing_mods_ids = set([region.face_metadata.page_identity.mods_id for region in regions
                                 if region.face_metadata is not None
                                 and region.face_metadata.page_identity is not None
                                 and region.face_metadata.page_identity.mods_id is not None])

        index = 1
        new_id = f"{prefix}_{str(index).zfill(padding)}"

        while new_id in existing_mods_ids:
            index += 1
            new_id = f"{prefix}_{str(index).zfill(padding)}"

        return new_id
