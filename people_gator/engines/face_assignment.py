import cv2
import logging
import numpy as np

from pydantic import BaseModel, ConfigDict
from collections import defaultdict

from people_gator.engines.face_entity_context import FaceEntityContext, assigned_caption

from people_gator.core.utils import find_text_in_bounding_box
from people_gator.core.layout import PeopleGatorFaceRegionLayout
from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine
from people_gator.enums import ProcessingMode


logger = logging.getLogger(__name__)


class FaceIdentifier(BaseModel):
    """A face identifier and its four bounding-box coordinates."""
    id: str
    coordinates: tuple[int, int, int, int]


class FaceAssignmentData:
    """One face crop, context image/text, relative center, and assignment result.

    Attributes:
        result: Optional assignment prediction, populated after the request.
    """

    def __init__(self, face_region, face_image, face_coordinates, context_image, context_text=None, caption_text=None, result=None, entity_context=None):
        """Initialize FaceAssignmentData from the supplied settings and data.

        Args:
            face_region: Face region to export or assign.
            face_image: Cropped face image.
            face_coordinates: Face center relative to context, in integer percentages.
            context_image: Cropped source context with marked faces.
            context_text: Optional OCR text overlapping the context crop.
            caption_text: Optional source-region caption.
            result: Structured model result, or None before assignment.
            entity_context: Selected source-grounded text evidence, or None for empty sections.
        """
        self.face_region = face_region
        self.face_image = face_image
        self.face_coordinates = face_coordinates
        self.context_image = context_image
        self.context_text = context_text
        self.caption_text = caption_text
        self.result = result
        self.entity_context = entity_context or {key: [] for key in (
            "caption_entities", "surrounding_entities", "page_entities", "document_entities")}

    def __repr__(self):
        """Return a diagnostic representation of the stored fields.

        Returns:
            A diagnostic string; it may contain document or person data.
        """
        return f"FaceAssignmentData(face_region={self.face_region}, face_image={self.face_image}, context_image={self.context_image}, context_text={self.context_text}, caption_text={self.caption_text}, result={repr(self.result)})"


class FaceAssignmentResult(BaseModel):
    """Normalized and source-text names proposed for one face."""
    name_normalized: str|None
    name_in_text: str|None

    def __repr__(self):
        """Return a diagnostic representation of the stored fields.

        Returns:
            A diagnostic string; it may contain document or person data.
        """
        return f"FaceAssignmentResult(name_normalized={self.name_normalized}, name_in_text={self.name_in_text})"


class LLMFaceAssignmentEngine(DocumentProcessingEngine, LLMBasedEngine):
    """Propose a person name per face using image and OCR context."""

    def __init__(self, config, device, config_path):
        """Initialize LLMFaceAssignmentEngine from the supplied settings and data.

        Args:
            config: INI configuration or engine section for this component.
            device: Processing device (torch device or cpu/gpu selection).
            config_path: Base directory for relative engine resource paths.
        """
        super().__init__(config, device, config_path)

        self.vertical_offset = self.config.getint("vertical_offset", 0)
        self.horizontal_offset = self.config.getint("horizontal_offset", 0)

    def process_document(self, document):
        """Process the document with the configured engine and return it.

        Args:
            document: Document to process or transfer; updated in place.

        Returns:
            The processed document (the same instance for the built-in engines).
        """
        for page_image, page_layout in document.pages_iterator():
            self.process_page(page_image, page_layout, document=document)

        return document

    def process_page(self, page_image, page_layout, document=None):
        """Request one prediction per face and apply names to the page.

        Args:
            page_image: Page image array in page-layout coordinates.
            page_layout: Page layout supplying regions, OCR, or source references.
            document: Original document for cross-page evidence, or None for page-only use.

        Returns:
            The page layout after in-place processing.
        """
        face_data = self.prepare_face_data(page_image, page_layout, document=document)
        logger.debug("Page %s: prepared %d LLM assignment requests", page_layout.id, len(face_data))

        for face_item in face_data:
            interactions = []
            try:
                result = self.llm_prompter(
                    data={
                        "face_coordinates": face_item.face_coordinates,
                        "context_text": face_item.context_text,
                        "caption_text": face_item.caption_text,
                        **face_item.entity_context
                    },
                    images=[face_item.face_image, face_item.context_image],
                    response_model=FaceAssignmentResult, interactions=interactions)
            finally:
                metadata = face_item.face_region.face_metadata
                if metadata is not None:
                    metadata.prompts.extend(dict(engine="LLM_FACE_ASSIGNMENT", **record) for record in interactions)
            face_item.result = result

        page_layout = self.update_layout(page_layout, face_data)

        return page_layout

    def prepare_face_data(self, page_image, page_layout, document=None) -> list[FaceAssignmentData]:
        """Build face request data from crops, relative coordinates, OCR, and captions.

        Args:
            page_image: Page image array in page-layout coordinates.
            page_layout: Page layout supplying regions, OCR, or source references.
            document: Original document for cross-page evidence, or None for page-only use.

        Returns:
            Request objects in face or source-region order.
        """
        face_data = []
        entity_context = FaceEntityContext(document)
        for i, region in enumerate(page_layout.regions):
            if isinstance(region, PeopleGatorFaceRegionLayout):
                face_x_min, face_y_min, face_x_max, face_y_max = region.get_polygon_bounding_box()
                face_image = page_image[face_y_min:face_y_max, face_x_min:face_x_max]

                source_region = region.source_region

                heights = [line.heights[0] + line.heights[1] for line in page_layout.lines_iterator()]
                median_line_height = np.median(heights) if heights else 0
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

                caption_text = assigned_caption(source_region)

                face_item = FaceAssignmentData(face_region=region,
                                               face_image=face_image,
                                               face_coordinates=face_coordinates,
                                               context_image=context_image,
                                               context_text=context_text,
                                               caption_text=caption_text,
                                               entity_context=entity_context.select(
                                                   page_layout, source_region, context_bbox, caption_text))

                face_data.append(face_item)

        return face_data

    def update_layout(self, page_layout, face_data: list[FaceAssignmentData]):
        """Apply nonblank names and preserve existing identities on unresolved predictions.

        Args:
            page_layout: Page layout supplying regions, OCR, or source references.
            face_data: Prepared face request objects with optional assignment results.

        Returns:
            The updated page layout.
        """
        for face_item in face_data:
            if face_item.result is None:
                logger.debug("Page %s: no assignment response for face %s", page_layout.id, face_item.face_region.id)
            face_region = face_item.face_region
            if face_item.result is not None:
                if face_region.face_metadata is None:
                    logger.warning('Face region %s has no face metadata, skipping update.', face_region.id)
                    continue

                name = face_item.result.name_normalized
                if isinstance(name, str) and name.strip():
                    face_region.face_metadata.page_identity.identity.name = name

        return page_layout


class BatchFaceAssignmentResultItem(BaseModel):
    """One batch prediction with an ID, relative center, and proposed names."""
    id: int
    coordinates: list[int]
    name_in_text: str|None
    name_normalized: str|None

    model_config = ConfigDict(extra="forbid")


class BatchFaceAssignmentResult(BaseModel):
    """Structured predictions for the faces in one source-region batch."""
    faces: list[BatchFaceAssignmentResultItem]


class BatchFaceAssignmentData:
    """A source-region context, ordered faces, and optional LLM batch result.

    Attributes:
        face_regions: Ordered regions corresponding to faces.
        result: Optional batch assignment prediction.
    """

    def __init__(self, context_text=None, caption_text=None, context_image=None, faces=None, face_regions=None, result=None, entity_context=None):
        """Initialize BatchFaceAssignmentData from the supplied settings and data.

        Args:
            context_text: Optional OCR text overlapping the context crop.
            caption_text: Optional source-region caption.
            context_image: Cropped source context with marked faces.
            faces: Ordered batch face descriptors (ID, coordinates, and color).
            face_regions: Ordered face regions corresponding to the batch descriptors.
            result: Structured model result, or None before assignment.
            entity_context: Selected source-grounded text evidence, or None for empty sections.
        """
        self.context_text = context_text
        self.caption_text = caption_text
        self.context_image = context_image
        self.faces = faces
        self.face_regions = face_regions
        self.result = result
        self.entity_context = entity_context or {key: [] for key in (
            "caption_entities", "surrounding_entities", "page_entities", "document_entities")}

    def to_dict(self):
        """Return faces, OCR text, and caption context for the prompt.
        """
        return {
            "faces": self.faces,
            "context_text": self.context_text,
            "caption_text": self.caption_text,
            **self.entity_context,
        }

    def __repr__(self):
        """Return a diagnostic representation of the stored fields.

        Returns:
            A diagnostic string; it may contain document or person data.
        """
        return f"BatchFaceAssignmentData(context_text={self.context_text}, caption_text={self.caption_text}, context_image={self.context_image}, faces={self.faces}, face_regions={self.face_regions}, result={self.result})"


class LLMBatchFaceAssignmentEngine(DocumentProcessingEngine, LLMBasedEngine):
    """Assign face groups using sequential or parallel LLM requests."""

    def __init__(self, config, device, config_path):
        """Initialize LLMBatchFaceAssignmentEngine from the supplied settings and data.

        Args:
            config: INI configuration or engine section for this component.
            device: Processing device (torch device or cpu/gpu selection).
            config_path: Base directory for relative engine resource paths.
        """
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

        self.processing_mode = ProcessingMode.from_string(self.config.get("processing_mode", "sequential"))

    def process_document(self, document):
        """Process the document with the configured engine and return it.

        Args:
            document: Document to process or transfer; updated in place.

        Returns:
            The processed document (the same instance for the built-in engines).
        """
        logger.debug("Document %s: batch assignment mode=%s", document.id, self.processing_mode.name)
        if self.processing_mode == ProcessingMode.DOCUMENT_PARALLEL:
            self.process_document_parallel(document)
        else:
            for page_image, page_layout in document.pages_iterator():
                self.process_page(page_image, page_layout, document=document)

        return document

    def process_document_parallel(self, document):
        """Assign source-region batches across the document using a process pool.

        Args:
            document: Document to process or transfer; updated in place.
        """
        all_face_data = []
        for page_image, page_layout in document.pages_iterator():
            face_data = self.prepare_face_data(page_image, page_layout, document=document)
            logger.debug("Page %s: prepared %d LLM assignment requests", page_layout.id, len(face_data))
            all_face_data.extend(face_data)

        data = [face_item.to_dict() for face_item in all_face_data]
        images = [[face_item.context_image] for face_item in all_face_data]
        interactions = []
        try:
            results = self.llm_prompter.process_parallel(
                data_list=data, images_list=images, response_model=BatchFaceAssignmentResult, interactions=interactions)
        finally:
            for face_item, records in zip(all_face_data, interactions):
                for face in face_item.face_regions:
                    metadata = face.face_metadata
                    if metadata is not None:
                        metadata.prompts.extend(dict(engine="LLM_BATCH_FACE_ASSIGNMENT", **record) for record in records)

        for face_item, result in zip(all_face_data, results):
            face_item.result = result

        self.update_layout(all_face_data)

    def process_page(self, page_image, page_layout, document=None):
        """Process one page in place and return its layout.

        Args:
            page_image: Page image array in page-layout coordinates.
            page_layout: Page layout supplying regions, OCR, or source references.
            document: Original document for cross-page evidence, or None for page-only use.

        Returns:
            The page layout after in-place processing.
        """
        face_data = self.prepare_face_data(page_image, page_layout, document=document)
        logger.debug("Page %s: prepared %d LLM assignment requests", page_layout.id, len(face_data))

        if self.processing_mode == ProcessingMode.PAGE_PARALLEL:
            data = [face_item.to_dict() for face_item in face_data]
            images = [[face_item.context_image] for face_item in face_data]
            interactions = []
            try:
                results = self.llm_prompter.process_parallel(
                    data_list=data, images_list=images, response_model=BatchFaceAssignmentResult, interactions=interactions)
            finally:
                for face_item, records in zip(face_data, interactions):
                    for face in face_item.face_regions:
                        metadata = face.face_metadata
                        if metadata is not None:
                            metadata.prompts.extend(dict(engine="LLM_BATCH_FACE_ASSIGNMENT", **record) for record in records)

            for face_item, result in zip(face_data, results):
                face_item.result = result

        else:
            for face_item in face_data:
                interactions = []
                try:
                    result = self.llm_prompter.process(
                        data=face_item.to_dict(), images=[face_item.context_image],
                        response_model=BatchFaceAssignmentResult, interactions=interactions)
                finally:
                    for face in face_item.face_regions:
                        metadata = face.face_metadata
                        if metadata is not None:
                            metadata.prompts.extend(dict(engine="LLM_BATCH_FACE_ASSIGNMENT", **record) for record in interactions)
                face_item.result = result

        self.update_layout(face_data)

        return page_layout

    def prepare_face_data(self, page_image, page_layout, document=None) -> list[BatchFaceAssignmentData]:
        """Build face request data from crops, relative coordinates, OCR, and captions.

        Args:
            page_image: Page image array in page-layout coordinates.
            page_layout: Page layout supplying regions, OCR, or source references.
            document: Original document for cross-page evidence, or None for page-only use.

        Returns:
            Request objects in face or source-region order.
        """
        face_data = []
        entity_context = FaceEntityContext(document)

        source_regions_mapping = defaultdict(list)
        for i, region in enumerate(page_layout.regions):
            if isinstance(region, PeopleGatorFaceRegionLayout):
                source_regions_mapping[region.source_region].append(region)

        median_line_height = 0
        lines = list(page_layout.lines_iterator())
        if len(lines) > 0:
            median_line_height = np.median([line.heights[0] + line.heights[1] for line in lines])
    
        vertical_offset = int(median_line_height * self.vertical_offset)
        horizontal_offset = int(median_line_height * self.horizontal_offset)

        for source_region, face_regions in source_regions_mapping.items():
            if len(face_regions) > self.max_people:
                logger.debug('Found %s face regions for source region %s, which exceeds the maximum of %s. Skipping this source region.', len(face_regions), source_region.id, self.max_people)
                continue

            source_x_min, source_y_min, source_x_max, source_y_max = source_region.get_polygon_bounding_box()
            context_x_min = max(0, source_x_min - horizontal_offset)
            context_y_min = max(0, source_y_min - vertical_offset)
            context_x_max = min(page_image.shape[1], source_x_max + horizontal_offset)
            context_y_max = min(page_image.shape[0], source_y_max + vertical_offset)

            context_bbox = (context_x_min, context_y_min, context_x_max, context_y_max)
            context_text = find_text_in_bounding_box(page_layout, context_bbox)

            context_image = np.copy(page_image[context_y_min:context_y_max, context_x_min:context_x_max])

            # Stable sorting retains page-region order for equal horizontal centers.
            sorted_face_regions = sorted(
                face_regions,
                key=lambda r: (r.get_polygon_bounding_box()[0] + r.get_polygon_bounding_box()[2]) / 2,
            )
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

            caption_text = assigned_caption(source_region)

            face_item = BatchFaceAssignmentData(
                context_text=context_text,
                caption_text=caption_text,
                context_image=context_image,
                faces=faces,
                face_regions=sorted_face_regions,
                result=None,
                entity_context=entity_context.select(
                    page_layout, source_region, context_bbox, caption_text)
            )

            face_data.append(face_item)

        return face_data

    def update_layout(self, face_data: list[BatchFaceAssignmentData]):
        """Apply nonblank names and preserve existing identities on unresolved predictions.

        Args:
            face_data: Prepared face request objects with optional assignment results.
        """
        for face_item in face_data:
            if face_item.result is None:
                logger.debug("Batch assignment has no response; preserving existing identities")
            if face_item.result is not None:
                for face_result in face_item.result.faces:
                    target_face_region = None
                    for face, face_region in zip(face_item.faces, face_item.face_regions):
                        if face["id"] == face_result.id and tuple(face["coordinates"]) == tuple(face_result.coordinates):
                            target_face_region = face_region
                            break

                    if target_face_region is None:
                        logger.warning('No matching face region found for face result %s with coordinates %s. Skipping update.', face_result.id, face_result.coordinates)
                        continue

                    if target_face_region.face_metadata is None:
                        logger.warning('Face region %s has no face metadata, skipping update.', target_face_region.id)
                        continue

                    name = face_result.name_normalized
                    if isinstance(name, str) and name.strip():
                        target_face_region.face_metadata.page_identity.identity.name = name
