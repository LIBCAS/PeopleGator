import logging

from abc import ABC, abstractmethod

from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout


class BaseEngine(ABC):
    def __init__(self, config, device, config_path, requires_lines=False):
        self.config = config
        self.device = device
        self.config_path = config_path
        self.requires_lines = requires_lines

        self.logger = logging.getLogger(self.__class__.__name__)


class PageProcessingEngine(BaseEngine):
    @abstractmethod
    def process_page(self, page_image, page_layout: PeopleGatorPageLayout):
        pass

class DocumentProcessingEngine(BaseEngine):
    @abstractmethod
    def process_document(self, document: PeopleGatorDocument):
        pass
