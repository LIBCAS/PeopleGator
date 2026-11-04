import logging

from abc import ABC, abstractmethod

from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout


class BaseEngine(ABC):
    """Common engine configuration, device, path base, and module logger.

    Attributes:
        config: Engine INI section.
        device: Selected processing device.
        config_path: Base directory for engine resources.
        logger: Logger in the concrete engine module.
    """

    def __init__(self, config, device, config_path):
        """Initialize BaseEngine from the supplied settings and data.

        Args:
            config: INI configuration or engine section for this component.
            device: Processing device (torch device or cpu/gpu selection).
            config_path: Base directory for relative engine resource paths.
        """
        self.config = config
        self.device = device
        self.config_path = config_path

        self.logger = logging.getLogger(self.__class__.__module__)
        self.logger.debug("Initializing engine %s on %s", self.__class__.__name__, device)


class DocumentProcessingEngine(BaseEngine):
    """Interface for engines that process and return a document."""


    @abstractmethod
    def process_document(self, document: PeopleGatorDocument) -> PeopleGatorDocument:
        """Process the document with the configured engine and return it.

        Args:
            document: Document to process or transfer; updated in place.

        Returns:
            The processed document (the same instance for the built-in engines).
        """
        pass
