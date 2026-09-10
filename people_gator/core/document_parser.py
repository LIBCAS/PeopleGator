import logging

from people_gator.core.layout import PeopleGatorDocument
from people_gator.engines import (FaceDetectionYoloEngine, FaceMatchingEngine, LLMNameDetectionEngine,
                                  NameClusteringEngine, LLMNameClusteringCheckEngine, LLMNameMatchingEngine,
                                  LLMNameDescriptionEngine)


logger = logging.getLogger(__name__)


class DocumentParser:
    def __init__(self, config, device, config_path):
        self.config = config
        self.device = device
        self.config_path = config_path

        self.engines = load_engines(config, device, config_path)

    def process_document(self, document: PeopleGatorDocument) -> PeopleGatorDocument:
        for engine in self.engines:
            logger.debug(f"Running {engine.__class__.__name__} engine")
            document = engine.process_document(document)

        return document


def engine_factory(config, config_path, device):
    method = config.get("METHOD", None)
    if method is None:
        logger.warning("No METHOD specified in config section.")
        return None

    engine = None

    if method == "FACE_DETECTION_YOLO":
        logger.info("Creating FaceDetectionYoloEngine engine")
        engine = FaceDetectionYoloEngine(config, device, config_path=config_path)

    elif method == "FACE_MATCHING":
        logger.info("Creating FaceMatchingEngine engine")
        engine = FaceMatchingEngine(config, device, config_path=config_path)

    elif method == "LLM_NAME_DETECTION":
        logger.info("Creating LLMNameDetectionEngine engine")
        engine = LLMNameDetectionEngine(config, device, config_path=config_path)

    elif method == "NAME_CLUSTERING":
        logger.info("Creating NameClusteringEngine engine")
        engine = NameClusteringEngine(config, device, config_path=config_path)

    elif method == "LLM_NAME_CLUSTERING_CHECK":
        logger.info("Creating LLMNameClusteringCheckEngine engine")
        engine = LLMNameClusteringCheckEngine(config, device, config_path=config_path)

    elif method == "LLM_NAME_MATCHING":
        logger.info("Creating LLMNameMatchingEngine engine")
        engine = LLMNameMatchingEngine(config, device, config_path=config_path)

    elif method == "LLM_NAME_DESCRIPTION":
        logger.info("Creating LLMNameDescriptionEngine engine")
        engine = LLMNameDescriptionEngine(config, device, config_path=config_path)

    else:
        logger.warning(f"Unknown METHOD specified in config section: {method}")

    return engine


def load_engines(config, device, config_path):
    engines = []
    for section_name in config.sections():
        logger.info(f"Loading engine for section: {section_name}")
        engine = engine_factory(config[section_name], config_path=config_path, device=device)
        if engine is not None:
            engines.append(engine)
        else:
            logger.info(f"Engine for section {section_name} could not be created.")

    return engines
