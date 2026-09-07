import numpy as np

from ultralytics import YOLO

from people_gator.core.layout import PeopleGatorFaceRegionLayout
from people_gator.core.utils import compose_path, config_get_list
from people_gator.engines import PageProcessingEngine, DocumentProcessingEngine


class FaceDetectionYoloEngine(PageProcessingEngine, DocumentProcessingEngine):
    def __init__(self, config, device, config_path):
        super().__init__(config, device, config_path)

        self.detector = YoloDetector(model_path=compose_path(self.config["MODEL_PATH"], self.config_path),
                                     device=self.device,
                                     detection_threshold=self.config.getfloat("DETECTION_THRESHOLD", 0.2),
                                     image_size=self.config.getint("IMAGE_SIZE", 640),
                                     agnostic_nms=self.config.getboolean("AGNOSTIC_NMS", False))

        self.categories = config_get_list(self.config, key="categories", fallback=None, make_lowercase=True)

    def process_document(self, document):
        for page_image, page_layout in document.pages_iterator():
            self.process_page(page_image, page_layout)

        return document

    def process_page(self, page_image, page_layout):
        regions = []
        regions_images = []

        for region in page_layout.regions:
            if self.categories is None or region.category.lower() in self.categories:
                x_min, y_min, x_max, y_max = region.get_polygon_bounding_box()
                region_image = page_image[y_min:y_max, x_min:x_max]

                if region_image.size == 0:
                    continue

                regions.append(region)
                regions_images.append(region_image)

        face_detections = self.detect_faces(regions_images)

        for region, region_image, region_face_detections in zip(regions, regions_images, face_detections):
            boxes = region_face_detections.boxes.data.cpu()
            for box in boxes:
                region_face_x_min, region_face_y_min, region_face_x_max, region_face_y_max, face_conf, face_class_id = box.tolist()
                region_x_min, region_y_min, _, _ = region.get_polygon_bounding_box()
                face_x_min = region_x_min + region_face_x_min
                face_y_min = region_y_min + region_face_y_min
                face_x_max = region_x_min + region_face_x_max
                face_y_max = region_y_min + region_face_y_max

                face_polygon = np.array([[face_x_min, face_y_min],
                                         [face_x_min, face_y_max],
                                         [face_x_max, face_y_max],
                                         [face_x_max, face_y_min],
                                         [face_x_min, face_y_min]])

                face_region = PeopleGatorFaceRegionLayout(id=self.get_next_region_id(page_layout, prefix="face"),
                                                          polygon=face_polygon,
                                                          category="face",
                                                          detection_confidence=face_conf)

                page_layout.regions.append(face_region)

        return page_layout

    def detect_faces(self, images):
        return self.detector(images)

    @staticmethod
    def get_next_region_id(page_layout, prefix, padding=3):
        existing_region_ids = set([region.id for region in page_layout.regions])

        index = 1
        new_id = f"{prefix}_{str(index).zfill(padding)}"

        while new_id in existing_region_ids:
            index += 1
            new_id = f"{prefix}_{str(index).zfill(padding)}"

        return new_id


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
