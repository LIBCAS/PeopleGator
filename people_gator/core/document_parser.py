import logging
from contextlib import nullcontext
from time import monotonic

from people_gator.core.layout import PeopleGatorDocument, PeopleGatorFaceRegionLayout
from people_gator.engines import FaceDetectionYoloEngine, LLMFaceAssignmentEngine, LLMBatchFaceAssignmentEngine, EntityMatchingEngine, LLMTextEntityDetectionEngine, LLMTextEntityClusteringEngine
from people_gator.core.services import UuidService
from people_gator.core.db import DatabaseApiService

logger = logging.getLogger(__name__)


class DocumentParser:
    """Configured engines in execution order and an optional app connection."""

    def __init__(self, config, device, config_path):
        """Initialize DocumentParser from the supplied settings and data.

        Args:
            config: INI configuration or engine section for this component.
            device: Processing device (torch device or cpu/gpu selection).
            config_path: Base directory for relative engine resource paths.
        """
        self.config = config
        self.device = device
        self.config_path = config_path

        self.db_api_service = None

        self.init_db_api_service()
        self.engines = load_engines(self.config, self.device, self.config_path, db_api_service=self.db_api_service)

    def init_db_api_service(self):
        """Initialize the app connection when a DB_API section exists."""
        if self.config.has_section("DB_API"):
            self.db_api_service = DatabaseApiService(self.config["DB_API"])

    def process_document(self, document: PeopleGatorDocument | None, import_from_app: bool = False, export_to_app: bool = False, drop_existing_annotations: bool = False, *, resume_from_checkpoint=None) -> PeopleGatorDocument:
        """Process the document with the configured engine and return it.

        Args:
            document: Document to process or transfer; updated in place.
            import_from_app: Whether to import app annotations first; defaults to False.
            export_to_app: Whether to export processing results; defaults to False.
            drop_existing_annotations: Whether to remove stored annotations before export; defaults to False.
            resume_from_checkpoint: Finalized checkpoint path; skips document loading/import and completed engines.

        Returns:
            The processed document (the same instance for the built-in engines).
        """
        from people_gator.core.checkpoints import CheckpointRun, CheckpointError
        directory = self.config.get('PARSE_FOLDER', 'PROCESSING_CHECKPOINTS', fallback='').strip()
        run = None
        if directory or resume_from_checkpoint:
            run = CheckpointRun(self.config, self.config_path, directory,
                dict(import_from_app=import_from_app, export_to_app=export_to_app,
                     drop_existing_annotations=drop_existing_annotations, device=str(self.device)),
                document=document, resume=resume_from_checkpoint)
            if len(run.pipeline) != len(self.engines):
                raise CheckpointError('Checkpointing requires every ENGINE section to load successfully')
            document = run.document
        with run.locked() if run else nullcontext():
            return self._process_document(document, import_from_app, export_to_app,
                                          drop_existing_annotations, run)

    def _process_document(self, document, import_from_app, export_to_app, drop_existing_annotations, run):
        """Run engines and final app export under the optional history lock.

        Args:
            document: Initial or restored complete document.
            import_from_app: Effective initial import option.
            export_to_app: Requested final app export.
            drop_existing_annotations: Requested destructive export option.
            run: Optional checkpoint history, holding the run lock.
        """
        logger.info("Processing document %s: %d pages, %d engines",
                    document.id, len(document.page_layouts), len(self.engines))
        if not document.page_layouts:
            logger.debug("Document %s has no pages", document.id)
        if (import_from_app or export_to_app) and self.db_api_service is None:
            logger.warning("Document %s: requested app operation skipped; DB_API is not configured", document.id)
        if import_from_app and self.db_api_service is not None and not (run and run.completed):
            logger.info("Importing document %s from PeopleGatorApp", document.id)
            document = import_document(document, self.db_api_service)

        start = len(run.completed) if run else 0
        for ordinal, engine in enumerate(self.engines[start:], start=start):
            logger.debug("Document %s: running engine %s", document.id, engine.__class__.__name__)
            if run:
                run.before_engine(ordinal)
            began = monotonic()
            document = engine.process_document(document)
            if run:
                run.save(document, ordinal, monotonic() - began)

        if export_to_app and self.db_api_service is not None:
            if run:
                run.before_export()
            logger.info("Exporting document %s to PeopleGatorApp", document.id)
            export_document(document, self.db_api_service, drop_existing_annotations=drop_existing_annotations)

        logger.info("Completed processing document %s", document.id)
        return document


def engine_factory(config, config_path, device, db_api_service=None):
    """Create the selected engine, or return None for missing/unknown METHOD.

    Args:
        config: INI configuration or engine section for this component.
        config_path: Base directory for relative engine resource paths.
        device: Processing device (torch device or cpu/gpu selection).
        db_api_service: Optional authenticated PeopleGatorApp client.
    """
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

    elif method == "TEXT_ENTITY_DETECTION":
        engine = LLMTextEntityDetectionEngine(config, device, config_path=config_path)

    elif method == "TEXT_ENTITY_CLUSTERING":
        engine = LLMTextEntityClusteringEngine(config, device, config_path=config_path)

    elif method == "ENTITY_MATCHING":
        logger.info("Creating EntityMatchingEngine engine")
        engine = EntityMatchingEngine(config, device, config_path=config_path, db_api_service=db_api_service)

    else:
        logger.warning('Unknown METHOD specified in config section: %s', method)

    return engine


def load_engines(config, device, config_path, db_api_service=None):
    """Return supported engines in configuration section order.

    Args:
        config: INI configuration or engine section for this component.
        device: Processing device (torch device or cpu/gpu selection).
        config_path: Base directory for relative engine resource paths.
        db_api_service: Optional authenticated PeopleGatorApp client.
    """
    engines = []
    for section_name in config.sections():
        if not section_name.startswith("ENGINE_"):
            continue

        logger.info('Loading engine for section: %s', section_name)
        engine = engine_factory(config[section_name], config_path=config_path, device=device, db_api_service=db_api_service)
        if engine is not None:
            engines.append(engine)
        else:
            logger.info('Engine for section %s could not be created.', section_name)

    return engines


def import_document(document: PeopleGatorDocument, db_api_service: DatabaseApiService) -> PeopleGatorDocument:
    """Append app face annotations to pages; log failures and preserve other pages.

    Args:
        document: Document to process or transfer; updated in place.
        db_api_service: Optional authenticated PeopleGatorApp client.
    """
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
            logger.error('Failed to get page info for page %s from PeopleGator App', page_layout.id)
            continue

        db_faces = db_api_service.get_faces_for_page(db_page['source_id'])
        if db_faces is None:
            logger.error('Failed to get faces for page %s from PeopleGator App', page_layout.id)
            continue

        for db_face in db_faces['items']:
            db_entity = None
            if db_face["entity_id"] is not None:
                db_entity = db_api_service.get_entity_info(db_face["entity_id"])
                if not db_entity:
                    logger.error('Failed to get entity info for entity %s from PeopleGator App', db_face['entity_id'])
                    continue

            face_region = PeopleGatorFaceRegionLayout.from_app_dict(db_face, db_entity, page_layout)
            page_layout.regions.append(face_region)

    logger.info("Finished import operations for document %s", document.id)
    return document


def export_document(document: PeopleGatorDocument, db_api_service: DatabaseApiService, drop_existing_annotations: bool = False):
    """Export document, page, face, image, and layout data, logging failed operations.

    Args:
        document: Document to process or transfer; updated in place.
        db_api_service: Optional authenticated PeopleGatorApp client.
        drop_existing_annotations: Whether to remove stored annotations before export; defaults to False.
    """
    if document.library is None:
        logger.error("Document library is not specified, cannot export to PeopleGator App")
        return

    if document.id is None:
        logger.error("Document ID is not specified, cannot export to PeopleGator App")
        return

    if document.name is None:
        logger.error("Document name is not specified, cannot export to PeopleGator App")
        return

    db_document = db_api_service.get_document_info(document.id, library=document.library)
    if not db_document:
        logger.info('Document %s does not exist in PeopleGator App, creating new document', document.id)
        db_document = db_api_service.create_document(document.id, document.name, library=document.library)
        if not db_document:
            logger.error('Failed to create document %s in PeopleGator App', document.id)
            return
    else:
        if drop_existing_annotations:
            logger.info('Dropping existing annotations for document %s in PeopleGator App', document.id)
            result = db_api_service.delete_document_annotations(document.id, library=document.library)
            if not result:
                logger.error('Failed to drop existing annotations for document %s in PeopleGator App', document.id)

    for page_image, page_layout in document.pages_iterator():
        db_page = db_api_service.get_page_info(document.id, page_layout.id, library=document.library)
        if not db_page:
            logger.debug('Page %s does not exist in PeopleGator App, creating new page', page_layout.id)
            db_page = db_api_service.create_page(page_layout.id, document.id, library=document.library)
            if not db_page:
                logger.error('Failed to create page %s in PeopleGator App', page_layout.id)
                continue
        else:
            logger.debug('Page %s already exists in PeopleGator App, updating existing page', page_layout.id)

        faces = [region for region in page_layout.regions if isinstance(region, PeopleGatorFaceRegionLayout)]
        for face_region in faces:
            db_face = db_api_service.create_face(face_region, db_page["source_id"])
            if not db_face:
                logger.error('Failed to create face %s in PeopleGator App', face_region.id)
            else:
                logger.debug("Created face %s in PeopleGatorApp", face_region.id)

        result = db_api_service.put_page_image(page_image, db_page['source_id'])
        if not result:
            logger.error('Failed to upload page image for page %s in PeopleGator App', page_layout.id)
        else:
            logger.debug('Uploaded page image for page %s in PeopleGator App', page_layout.id)

        result = db_api_service.put_page_layout(page_layout.to_app_dict(), db_page['source_id'])
        if not result:
            logger.error('Failed to upload page layout for page %s in PeopleGator App', page_layout.id)
        else:
            logger.debug('Uploaded page layout for page %s in PeopleGator App', page_layout.id)

    logger.info("Finished export operations for document %s", document.id)
