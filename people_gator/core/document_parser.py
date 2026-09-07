from people_gator.core.layout import PeopleGatorDocument
from people_gator.engines import FaceDetectionEngine


class DocumentParser:
    def __init__(self, config, device, config_path):
        self.config = config
        self.device = device
        self.config_path = config_path

    def process_document(self, document: PeopleGatorDocument) -> PeopleGatorDocument:
        return document
