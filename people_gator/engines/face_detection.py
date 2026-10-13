import numpy as np

from ultralytics import YOLO

from people_gator.core.layout import (PeopleGatorFaceRegionLayout, PeopleGatorFaceMetadata, Position,
                                      PeopleGatorPageIdentity, PeopleGatorIdentity, get_next_mods_id,
                                      get_next_region_id)
from people_gator.core.utils import compose_path, config_get_list
from people_gator.core.services import UuidService
from people_gator.engines import DocumentProcessingEngine


class FaceDetectionYoloEngine(DocumentProcessingEngine):
    def __init__(self, config, device, config_path):
        super().__init__(config, device, config_path)

        self.detector = YoloDetector(model_path=compose_path(self.config["MODEL_PATH"], self.config_path),
                                     device=self.device,
                                     detection_threshold=self.config.getfloat("DETECTION_THRESHOLD", 0.2),
                                     image_size=self.config.getint("IMAGE_SIZE", 640),
                                     agnostic_nms=self.config.getboolean("AGNOSTIC_NMS", False))

        self.categories = config_get_list(self.config, key="categories", fallback=None, make_lowercase=True)

        self.uuid_service = UuidService()

    def process_document(self, document):
        for page_image, page_layout in document.pages_iterator():
            self.process_page(page_image, page_layout)

        return document

    def process_page(self, page_image, page_layout):
        regions = []
        regions_images = []

        for region in page_layout.regions:
            if self.categories is None or region.category is not None and region.category.lower() in self.categories:
                x_min, y_min, x_max, y_max = region.get_polygon_bounding_box()
                region_image = page_image[y_min:y_max, x_min:x_max]

                if region_image.size == 0:
                    continue

                regions.append(region)
                regions_images.append(region_image)

        if len(regions_images) == 0:
            return page_layout

        face_detections = self.detect_faces(regions_images)

        for region, region_image, region_face_detections in zip(regions, regions_images, face_detections):
            boxes = region_face_detections.boxes.data.cpu()
            keypoints = region_face_detections.keypoints.data.cpu()
            for face_box, face_keypoints in zip(boxes, keypoints):
                region_face_x_min, region_face_y_min, region_face_x_max, region_face_y_max, face_conf, face_class_id = face_box.tolist()
                region_x_min, region_y_min, _, _ = region.get_polygon_bounding_box()
                face_x_min = region_x_min + region_face_x_min
                face_y_min = region_y_min + region_face_y_min
                face_x_max = region_x_min + region_face_x_max
                face_y_max = region_y_min + region_face_y_max

                left_eye_x, left_eye_y, left_eye_conf = face_keypoints[0].tolist()
                right_eye_x, right_eye_y, right_eye_conf = face_keypoints[1].tolist()
                nose_x, nose_y, nose_conf = face_keypoints[2].tolist()
                left_mouth_corner_x, left_mouth_corner_y, left_mouth_corner_conf = face_keypoints[3].tolist()
                right_mouth_corner_x, right_mouth_corner_y, right_mouth_corner_conf = face_keypoints[4].tolist()

                left_eye_x += region_x_min
                left_eye_y += region_y_min
                right_eye_x += region_x_min
                right_eye_y += region_y_min
                nose_x += region_x_min
                nose_y += region_y_min
                left_mouth_corner_x += region_x_min
                left_mouth_corner_y += region_y_min
                right_mouth_corner_x += region_x_min
                right_mouth_corner_y += region_y_min

                face_polygon = np.array([[face_x_min, face_y_min],
                                         [face_x_min, face_y_max],
                                         [face_x_max, face_y_max],
                                         [face_x_max, face_y_min],
                                         [face_x_min, face_y_min]])

                face_region_id = get_next_region_id(page_layout, prefix="face")
                person_region_id = get_next_region_id(page_layout, prefix="person")

                face_mods_id = get_next_mods_id(page_layout, prefix="MODS_FACE")
                person_mods_id = get_next_mods_id(page_layout, prefix="MODS_PERSON")

                page_identity = PeopleGatorPageIdentity(tag_id=person_region_id,
                                                        mods_id=person_mods_id,
                                                        identity=PeopleGatorIdentity(peoplegator_id=None,
                                                                                     name=None))

                face_metadata = PeopleGatorFaceMetadata(tag_id=face_region_id,
                                                        mods_id=face_mods_id,
                                                        page_identity=page_identity,
                                                        left_eye_position=Position(x=left_eye_x, y=left_eye_y),
                                                        right_eye_position=Position(x=right_eye_x, y=right_eye_y),
                                                        nose_position=Position(x=nose_x, y=nose_y),
                                                        left_mouth_corner_position=Position(x=left_mouth_corner_x, y=left_mouth_corner_y),
                                                        right_mouth_corner_position=Position(x=right_mouth_corner_x, y=right_mouth_corner_y),
                                                        mods_uuid=str(self.uuid_service()),
                                                        used_ai_models={"model.face-detection": "yolo"},
                                                        confidence=face_conf)

                face_region = PeopleGatorFaceRegionLayout(id=face_region_id,
                                                          polygon=face_polygon,
                                                          category="face",
                                                          detection_confidence=face_conf,
                                                          source_region=region,
                                                          face_metadata=face_metadata)

                page_layout.regions.append(face_region)

        return page_layout

    def detect_faces(self, images):
        return self.detector(images)


class YoloDetector:
    def __init__(self, model_path, device, detection_threshold=0.2, image_size=640, agnostic_nms=False):
        self.model = YOLO(model_path).to(device)
        self.detection_threshold = detection_threshold
        self.image_size = image_size
        self.agnostic_nms = agnostic_nms

    def __call__(self, *args, **kwargs):
        return self.detect(*args, **kwargs)

    def detect(self, data):
        results = self.model(data, conf=self.detection_threshold, imgsz=self.image_size, verbose=False, agnostic_nms=self.agnostic_nms)
        return results

    @property
    def names(self):
        return self.model.names
