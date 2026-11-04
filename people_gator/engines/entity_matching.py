import logging

from pydantic import BaseModel

from anno_page.core.layout import AnnoPageRegionLayout

from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine
from people_gator.core.layout import PeopleGatorDocument, PeopleGatorFaceRegionLayout, PeopleGatorPageIdentity, PeopleGatorIdentity


logger = logging.getLogger(__name__)


class EntityMatchingResult(BaseModel):
    """An optional candidate index and name returned by LLM disambiguation."""
    item_id: int|None
    name: str|None


class EntityMatchingEngine(DocumentProcessingEngine, LLMBasedEngine):
    """Resolve proposed face names against PeopleGatorApp person records."""

    def __init__(self, config, device, config_path, db_api_service=None):
        """Initialize EntityMatchingEngine from the supplied settings and data.

        Args:
            config: INI configuration or engine section for this component.
            device: Processing device (torch device or cpu/gpu selection).
            config_path: Base directory for relative engine resource paths.
            db_api_service: Optional authenticated PeopleGatorApp client.
        """
        super().__init__(config, device, config_path)

        self.db_api_service = db_api_service

    def process_document(self, document: PeopleGatorDocument):
        """Process the document with the configured engine and return it.

        Args:
            document: Document to process or transfer; updated in place.

        Returns:
            The processed document (the same instance for the built-in engines).
        """
        if self.db_api_service is None:
            logger.warning("Database API service is not initialized. Skipping entity matching.")
            return document

        for page_layout in document.page_layouts:
            self.process_page(page_layout)

        return document

    def process_page(self, page_layout):
        """Process one page in place and return its layout.

        Args:
            page_layout: Page layout supplying regions, OCR, or source references.

        Returns:
            The page layout after in-place processing.
        """
        if self.db_api_service is None:
            logger.warning("Database API service is not initialized. Skipping entity matching.")
            return page_layout

        for region in page_layout.regions:
            if isinstance(region, PeopleGatorFaceRegionLayout):
                if region.face_metadata is not None:
                    name = region.face_metadata.identity_name
                    if name is not None:
                        db_entities = self.db_api_service.search_entities(query=name)["items"]

                        logger.debug("Page %s face %s: %d candidate entities", page_layout.id, region.id, len(db_entities))
                        if len(db_entities) > 1:
                            caption = None
                            if isinstance(region.source_region, AnnoPageRegionLayout) and region.source_region.graphical_metadata is not None:
                                caption = region.source_region.graphical_metadata.title

                            db_entities = self.match_entity(name, caption, db_entities)

                        if len(db_entities) == 1:
                            region.face_metadata.page_identity.identity.peoplegator_id = db_entities[0]["entity_id"]
                            logger.debug("Page %s face %s: matched an existing entity", page_layout.id, region.id)

                        elif len(db_entities) == 0:
                            peoplegator_id = self.db_api_service.create_entity(name=name)["entity_id"]
                            region.face_metadata.page_identity.identity.peoplegator_id = peoplegator_id
                            logger.debug("Page %s face %s: created an entity", page_layout.id, region.id)

                        else:
                            region.face_metadata.page_identity.identity.peoplegator_id = None
                            logger.warning("Page %s face %s: ambiguous candidates; identity left unresolved", page_layout.id, region.id)

        return page_layout

    def match_entity(self, name, caption, db_entities):
        """Ask the LLM to select a candidate and return the matching candidate list.

        Args:
            name: Proposed person name, or None when unknown.
            caption: Optional source-region caption for disambiguation.
            db_entities: Candidate app entity records.
        """
        entities = self.prepare_entities(db_entities)
        result = self.llm_prompter(data={
                                       "name": name,
                                       "context": caption,
                                       "entities": entities
                                   },
                                   response_model=EntityMatchingResult)

        entities = self.postprocess_entities(entities, result)
        return entities

    @staticmethod
    def prepare_entities(db_entities):
        """Return candidate copies with sequential item_id fields for disambiguation.

        Args:
            db_entities: Candidate app entity records.
        """
        entities = []
        for i, entity in enumerate(db_entities):
            entities.append({
                "item_id": i,
                **entity
            })

        return entities

    @staticmethod
    def postprocess_entities(entities, result: EntityMatchingResult):
        """Return the candidate whose ID and name match, or an empty list.

        Args:
            entities: Indexed candidate entity records.
            result: Structured model result, or None before assignment.
        """
        if result.item_id is not None and result.name is not None:
            for entity in entities:
                if entity["item_id"] == result.item_id and entity["name"] == result.name:
                    return [entity]
        logger.debug("Entity disambiguation returned no matching candidate")
        return []
