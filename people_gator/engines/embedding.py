"""Local face embedding inference using the timm ArcFace input convention."""

import cv2
import numpy as np
import torch
from anno_page.core.embedding import ObjectEmbedding, ProcessingInfo

from people_gator.core.services import DateTimeService
from people_gator.engines.base import DocumentProcessingEngine
from people_gator.globals import software_name, software_version


# Reference landmarks from the model author's timm-face IJB evaluation.
FACE_SIZE = (112, 112)
ARCFACE_LANDMARKS = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
    [41.5493, 92.3655], [70.7299, 92.2041],
], dtype=np.float32)

# AnnoPage's dtype helper imports its Transformers engine package and falls
# back on unknown values. This stage uses the same names with explicit selection.
PRECISIONS = {
    "float32": torch.float32, "fp32": torch.float32,
    "float16": torch.float16, "fp16": torch.float16,
    "bfloat16": torch.bfloat16, "bf16": torch.bfloat16,
}


def _face_image(page_image, face):
    """Return the aligned BGR face, a resized crop, or None for an empty crop.

    Args:
        page_image: Original BGR page pixels.
        face: Face region with page-coordinate landmarks and polygon.
    """
    metadata = face.face_metadata
    landmarks = (
        metadata.left_eye_position, metadata.right_eye_position,
        metadata.nose_position, metadata.left_mouth_corner_position,
        metadata.right_mouth_corner_position,
    )
    if all(point is not None for point in landmarks):
        points = np.array([(point.x, point.y) for point in landmarks], dtype=np.float32)
        if np.isfinite(points).all():
            try:
                transform, _ = cv2.estimateAffinePartial2D(
                    points, ARCFACE_LANDMARKS, ransacReprojThreshold=float("inf"),
                )
                if (transform is not None and np.isfinite(transform).all()
                        and np.any(transform[0, :2])):
                    return cv2.warpAffine(page_image, transform, FACE_SIZE, flags=cv2.INTER_CUBIC)
            except cv2.error:
                # OpenCV could not align the landmarks. Use the bounding box below.
                pass

    x_min, y_min, x_max, y_max = face.get_polygon_bounding_box()
    crop = page_image[max(0, y_min):max(0, y_max), max(0, x_min):max(0, x_max)]
    if crop.size == 0:
        return None
    return cv2.resize(crop, FACE_SIZE, interpolation=cv2.INTER_CUBIC)


class FaceEmbeddingEngine(DocumentProcessingEngine):
    """Append structured embeddings to existing face regions."""

    def __init__(self, config, device, config_path):
        """Load the configured pretrained model once in evaluation mode.

        Args:
            config: INI section for the face embedding stage.
            device: Device on which the model runs.
            config_path: Base directory for engine resources.
        """
        super().__init__(config, device, config_path)

        import timm

        self.model_name = self.config["MODEL"]
        self.precision = PRECISIONS[self.config.get("PRECISION", "float32").lower()]
        self.decimal_places = self.config.getint("DECIMAL_PLACES", None)
        self.model = timm.create_model(f"hf-hub:{self.model_name}", pretrained=True)
        self.model.to(device=self.device, dtype=self.precision).eval()

    def process_document(self, document):
        """Attach embeddings and return the original document.

        Args:
            document: Document with original face regions and page images.
        """
        for page in document.page_layouts:
            faces = page.faces
            if not faces:
                continue
            page_image = document.get_page_image(page)
            for face in faces:
                image = _face_image(page_image, face)
                if image is None:
                    continue

                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                # Scale pixels to [0, 1], then apply mean and std of 0.5.
                pixels = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0)
                pixels = (pixels.float() / 255 - 0.5) / 0.5
                pixels = pixels.to(device=self.device, dtype=self.precision)
                with torch.no_grad():
                    features = self.model(pixels)
                    values = torch.nn.functional.normalize(features.float(), dim=1)[0].cpu().tolist()
                if self.decimal_places is not None:
                    values = [round(value, self.decimal_places) for value in values]

                face.embeddings.append(ObjectEmbedding(
                    id=f"uuid:{face.face_metadata.mods_uuid}",
                    tag_id=face.id,
                    page_uuid=page.id,
                    category="face",
                    embedding=values,
                    processing_info=ProcessingInfo(
                        system=software_name,
                        version=software_version,
                        datetime=DateTimeService.get_datetime_now().isoformat(),
                        model=self.model_name,
                        decimal_places=self.decimal_places,
                        precision=str(features.dtype),
                    ),
                ))
        return document
