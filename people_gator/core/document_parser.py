import logging

from people_gator.core.layout import PeopleGatorDocument, PeopleGatorFaceRegionLayout
from people_gator.engines import FaceDetectionYoloEngine, LLMFaceAssignmentEngine, LLMBatchFaceAssignmentEngine, EntityMatchingEngine
from people_gator.core.services import UuidService
from people_gator.core.db import DatabaseApiService

logger = logging.getLogger(__name__)


class DocumentParser:
    def __init__(self, config, device, config_path):
        self.config = config
        self.device = device
        self.config_path = config_path

        self.db_api_service = None

        self.init_db_api_service()
        self.engines = load_engines(self.config, self.device, self.config_path, db_api_service=self.db_api_service)

    def init_db_api_service(self):
        if self.config.has_section("DB_API"):
            self.db_api_service = DatabaseApiService(self.config["DB_API"])

    def process_document(self, document: PeopleGatorDocument, import_from_app: bool = False, export_to_app: bool = False) -> PeopleGatorDocument:
        if import_from_app and self.db_api_service is not None:
            logger.info("Importing document from PeopleGator App")
            document = import_document(document, self.db_api_service)

        for engine in self.engines:
            logger.debug(f"Running {engine.__class__.__name__} engine")
            document = engine.process_document(document)

        if export_to_app and self.db_api_service is not None:
            logger.info("Exporting document to PeopleGator App")
            export_document(document, self.db_api_service)

        return document


def engine_factory(config, config_path, device, db_api_service=None):
    method = config.get("METHOD", None)
    if method is None:
        logger.warning("No METHOD specified in config section.")
        return None

    engine = None

    if method == "FACE_DETECTION_YOLO":
        logger.info("Creating FaceDetectionYoloEngine engine")
        engine = FaceDetectionYoloEngine(config, device, config_path=config_path)

    elif method == "LLM_FACE_ASSIGNMENT":
        logger.info("Creating FaceAssignmentEngine engine")
        engine = LLMFaceAssignmentEngine(config, device, config_path=config_path)

    elif method == "LLM_BATCH_FACE_ASSIGNMENT":
        logger.info("Creating LLMBatchFaceAssignmentEngine engine")
        engine = LLMBatchFaceAssignmentEngine(config, device, config_path=config_path)

    elif method == "ENTITY_MATCHING":
        logger.info("Creating EntityMatchingEngine engine")
        engine = EntityMatchingEngine(config, device, config_path=config_path, db_api_service=db_api_service)

    else:
        logger.warning(f"Unknown METHOD specified in config section: {method}")

    return engine


def load_engines(config, device, config_path, db_api_service=None):
    engines = []
    for section_name in config.sections():
        if not section_name.startswith("ENGINE_"):
            continue

        logger.info(f"Loading engine for section: {section_name}")
        engine = engine_factory(config[section_name], config_path=config_path, device=device, db_api_service=db_api_service)
        if engine is not None:
            engines.append(engine)
        else:
            logger.info(f"Engine for section {section_name} could not be created.")

    return engines


def import_document(document: PeopleGatorDocument, db_api_service: DatabaseApiService) -> PeopleGatorDocument:
    if document.library is None:
        logger.error("Document library is not specified, cannot import from PeopleGator App")
        return document

    if document.id is None:
        logger.error("Document ID is not specified, cannot import from PeopleGator App")
        return document

    db_document = db_api_service.get_document_info(document.id, library=document.library)
    if not db_document:
        logger.error("Failed to get document info from PeopleGator App")
        return document

    for page_layout in document.page_layouts:
        db_page = db_api_service.get_page_info(document.id, page_layout.id, library=document.library)
        if not db_page:
            logger.error(f"Failed to get page info for page {page_layout.id} from PeopleGator App")
            continue

        db_faces = db_api_service.get_faces_for_page(db_page['source_id'])
        if db_faces is None:
            logger.error(f"Failed to get faces for page {page_layout.id} from PeopleGator App")
            continue

        for db_face in db_faces['items']:
            db_entity = None
            if db_face["entity_id"] is not None:
                db_entity = db_api_service.get_entity_info(db_face["entity_id"])
                if not db_entity:
                    logger.error(f"Failed to get entity info for entity {db_face['entity_id']} from PeopleGator App")
                    continue

            face_region = PeopleGatorFaceRegionLayout.from_app_dict(db_face, db_entity, page_layout)
            page_layout.regions.append(face_region)

    return document


def export_document(document: PeopleGatorDocument, db_api_service: DatabaseApiService):
    if document.library is None:
        logger.error("Document library is not specified, cannot export to PeopleGator App")
        return

    if document.id is None:
        logger.error("Document ID is not specified, cannot export to PeopleGator App")
        return

    if document.name is None:
        logger.error("Document name is not specified, cannot export to PeopleGator App")
        return

    db_document = db_api_service.create_document(document.id, document.name, library=document.library)
    if not db_document:
        logger.error("Failed to create document in PeopleGator App")
        return

    for page_image, page_layout in document.pages_iterator():
        faces = [region for region in page_layout.regions if isinstance(region, PeopleGatorFaceRegionLayout)]
        if len(faces) > 0:
            db_page = db_api_service.create_page(page_layout.id, document.id, library=document.library)
            if not db_page:
                logger.error(f"Failed to create page {page_layout.id} in PeopleGator App")
                continue

            for face_region in faces:
                db_face = db_api_service.create_face(face_region, db_page["source_id"])
                if not db_face:
                    logger.error(f"Failed to create face {face_region.id} in PeopleGator App")

            result = db_api_service.put_page_image(page_image, db_page['source_id'])
            if not result:
                logger.error(f"Failed to upload page image for page {page_layout.id} in PeopleGator App")

            result = db_api_service.put_page_layout(page_layout.to_app_dict(), db_page['source_id'])
            if not result:
                logger.error(f"Failed to upload page layout for page {page_layout.id} in PeopleGator App")
