import cv2
import logging
import numpy as np

from pydantic import BaseModel, ConfigDict
from collections import defaultdict
from copy import deepcopy

from shapely.geometry import Polygon, box

from people_gator.core.utils import (find_text_in_bounding_box, assigned_caption,
                                     caption_mentions)
from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine
from people_gator.enums import ProcessingMode


logger = logging.getLogger(__name__)


def select_entity_context(page, source_region, context_bbox, caption_text, document=None):
    """Build evidence for one selection using the same preparation as face batches.

    Args:
        page: Original page containing the face.
        source_region: Image region with optional caption metadata.
        context_bbox: Image crop in page coordinates.
        caption_text: Assigned title or None.
        document: Original document, or None for standalone page processing.
    """
    return select_entity_contexts(page, [(source_region, context_bbox, caption_text)], document)[0]


def _off_page_entities(page, document, membership, occurrences):
    """Group off-page evidence once, preserving encounter order and on-page exclusion.

    Args:
        page: Current page excluded from document evidence.
        document: Original document, or None for standalone processing.
        membership: First owning cluster keyed by mention identity.
        occurrences: Current page's resolved original mentions.
    """
    if document is None:
        return []
    result = []
    on_page = {id(membership[id(m)]) for m, _ in occurrences if id(m) in membership}
    seen, groups = set(), {}
    for pi, other_page in enumerate(document.page_layouts):
        if other_page is page:
            continue
        _, other_occurrences = other_page.resolve_text_entities(pi)
        for mention, sources in other_occurrences:
            if id(mention) in seen:
                continue
            seen.add(id(mention))
            cluster = membership.get(id(mention))
            if cluster is not None and id(cluster) in on_page:
                continue
            record = mention.to_evidence_record(other_page, pi, sources, 'document')
            if cluster is None:
                result.append(record)
            else:
                if id(cluster) not in groups:
                    group = dict(provenance='document', provisional=True, name=cluster.name,
                                 description=cluster.description, short_description=cluster.short_description,
                                 aliases=[], sources=[])
                    groups[id(cluster)] = group
                    result.append(group)
                groups[id(cluster)]['sources'].append(record)
    for group in groups.values():
        group['aliases'] = list(dict.fromkeys(record['name'] for record in group['sources']))
    return result


def select_entity_contexts(page, selections, document=None):
    """Prepare independent face payloads, reusing invariant sources within this call.

    Args:
        page: Original page containing the requests.
        selections: Ordered (source region, crop bounds, caption text) tuples.
        document: Original document, or None for standalone page processing.

    Returns:
        Ordered independent payloads. Caption-only requests do not resolve other
        pages. Reuse ends when this function returns, before any model decisions.
    """
    if not selections:
        return []
    page_index = next(i for i, p in enumerate(document.page_layouts) if p is page) if document is not None else None
    page_index, occurrences = page.resolve_text_entities(page_index)
    membership = document.text_entity_membership() if document is not None else {}
    captions_by_source, selected = {}, {}
    document_entities = None
    results = []
    for source_region, context_bbox, caption_text in selections:
        selection_key = (id(source_region), tuple(context_bbox), caption_text)
        if selection_key in selected:
            results.append(deepcopy(selected[selection_key]))
            continue
        caption_key = (id(source_region), caption_text)
        if caption_key not in captions_by_source:
            captions_by_source[caption_key] = caption_mentions(page, source_region, caption_text, occurrences)
        captions = captions_by_source[caption_key]
        result = {key: [] for key in ('caption_entities', 'surrounding_entities', 'page_entities', 'document_entities')}
        result['caption_entities'] = [m.to_evidence_record(page, page_index, sources, 'caption', membership.get(id(m)))
                                      for m, sources in captions]
        if not captions:
            crop = box(*context_bbox)
            for mention, sources in occurrences:
                cluster = membership.get(id(mention))
                result['page_entities'].append(mention.to_evidence_record(page, page_index, sources, 'page', cluster))
                if any(Polygon(line.polygon).intersection(crop).area > 0 for _, line in sources):
                    result['surrounding_entities'].append(mention.to_evidence_record(page, page_index, sources, 'surrounding', cluster))
            if document_entities is None:
                document_entities = _off_page_entities(page, document, membership, occurrences)
            result['document_entities'] = deepcopy(document_entities)
        selected[selection_key] = result
        results.append(result)
    return results


def _page_offsets(page, vertical, horizontal):
    """Compute OCR-height-based crop margins once per prepared page.

    Args:
        page: Original page with OCR line heights.
        vertical: Configured vertical multiplier.
        horizontal: Configured horizontal multiplier.
    """
    heights = [line.heights[0] + line.heights[1] for line in page.lines_iterator()]
    median = np.median(heights) if heights else 0
    return int(median * vertical), int(median * horizontal)


def _context_crop(page_image, source_region, vertical_offset, horizontal_offset):
    """Clip source context to the image and copy it before drawing face markers.

    Args:
        page_image: Original image array.
        source_region: Original image region.
        vertical_offset: Vertical margin in pixels.
        horizontal_offset: Horizontal margin in pixels.
    """
    left, top, right, bottom = source_region.get_polygon_bounding_box()
    bounds = (max(0, left - horizontal_offset), max(0, top - vertical_offset),
              min(page_image.shape[1], right + horizontal_offset), min(page_image.shape[0], bottom + vertical_offset))
    x0, y0, x1, y1 = bounds
    return bounds, np.copy(page_image[y0:y1, x0:x1])


def _mark_face(context_image, bounds, face_bounds, color):
    """Draw a face and return its center as integer context percentages.

    Args:
        context_image: Independent context crop to mark.
        bounds: Context bounds in page coordinates.
        face_bounds: Face bounds in page coordinates.
        color: OpenCV marker color.
    """
    x0, y0, x1, y1 = bounds
    left, top, right, bottom = face_bounds
    cv2.rectangle(context_image, (left - x0, top - y0), (right - x0, bottom - y0), color, 3)
    return (round(100 * ((left + right) / 2 - x0) / (x1 - x0)),
            round(100 * ((top + bottom) / 2 - y0) / (y1 - y0)))


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
                    metadata.record_interactions("LLM_FACE_ASSIGNMENT", interactions)
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
        selections = []
        faces = page_layout.faces
        if not faces:
            return face_data
        vertical_offset, horizontal_offset = _page_offsets(page_layout, self.vertical_offset, self.horizontal_offset)
        for region in faces:
            face_bounds = region.get_polygon_bounding_box()
            left, top, right, bottom = face_bounds
            face_image = page_image[top:bottom, left:right]
            source_region = region.source_region
            context_bbox, context_image = _context_crop(page_image, source_region, vertical_offset, horizontal_offset)
            face_coordinates = _mark_face(context_image, context_bbox, face_bounds, (0, 255, 0))
            context_text = find_text_in_bounding_box(page_layout, context_bbox)
            caption_text = assigned_caption(source_region)
            face_data.append(FaceAssignmentData(
                face_region=region, face_image=face_image, face_coordinates=face_coordinates,
                context_image=context_image, context_text=context_text, caption_text=caption_text))
            selections.append((source_region, context_bbox, caption_text))

        for item, context in zip(face_data, select_entity_contexts(page_layout, selections, document)):
            item.entity_context = context
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

        self._assign_parallel(all_face_data)
        self.update_layout(all_face_data)

    def _assign_parallel(self, face_data):
        """Assign ordered batches, retaining all attempts before propagating errors.

        Args:
            face_data: Prepared batches for either one page or the whole document.
        """
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
                        metadata.record_interactions("LLM_BATCH_FACE_ASSIGNMENT", records)

        for face_item, result in zip(face_data, results):
            face_item.result = result

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
            self._assign_parallel(face_data)

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
                            metadata.record_interactions("LLM_BATCH_FACE_ASSIGNMENT", interactions)
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
        selections = []

        source_regions_mapping = defaultdict(list)
        for region in page_layout.faces:
            source_regions_mapping[region.source_region].append(region)
        vertical_offset, horizontal_offset = _page_offsets(page_layout, self.vertical_offset, self.horizontal_offset)

        for source_region, face_regions in source_regions_mapping.items():
            if len(face_regions) > self.max_people:
                logger.debug('Found %s face regions for source region %s, which exceeds the maximum of %s. Skipping this source region.', len(face_regions), source_region.id, self.max_people)
                continue

            context_bbox, context_image = _context_crop(page_image, source_region, vertical_offset, horizontal_offset)
            context_text = find_text_in_bounding_box(page_layout, context_bbox)

            # Stable sorting retains page-region order for equal horizontal centers.
            sorted_face_regions = sorted(
                face_regions,
                key=lambda r: (r.get_polygon_bounding_box()[0] + r.get_polygon_bounding_box()[2]) / 2,
            )
            faces = []
            for i, face_region in enumerate(sorted_face_regions):
                face_color_name = list(self.colors.keys())[i % len(self.colors)]
                face_color = self.colors[face_color_name]

                face_coordinates = _mark_face(context_image, context_bbox, face_region.get_polygon_bounding_box(), face_color[::-1])

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
                result=None
            )

            face_data.append(face_item)
            selections.append((source_region, context_bbox, caption_text))

        for item, context in zip(face_data, select_entity_contexts(page_layout, selections, document)):
            item.entity_context = context
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
