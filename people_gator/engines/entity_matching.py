import logging

from pydantic import BaseModel

from anno_page.core.layout import AnnoPageRegionLayout

from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine
from people_gator.core.layout import PeopleGatorDocument, PeopleGatorFaceRegionLayout, PeopleGatorPageIdentity, PeopleGatorIdentity


logger = logging.getLogger(__name__)


class EntityMatchingResult(BaseModel):
    item_id: int|None
    name: str|None


class EntityMatchingEngine(DocumentProcessingEngine, LLMBasedEngine):
    def __init__(self, config, device, config_path, db_api_service=None):
        super().__init__(config, device, config_path)

        self.db_api_service = db_api_service

    def process_document(self, document: PeopleGatorDocument):
        if self.db_api_service is None:
            logger.warning("Database API service is not initialized. Skipping entity matching.")
            return document

        for page_layout in document.page_layouts:
            self.process_page(page_layout)

        return document

    def process_page(self, page_layout):
        if self.db_api_service is None:
            logger.warning("Database API service is not initialized. Skipping entity matching.")
            return page_layout

        for region in page_layout.regions:
            if isinstance(region, PeopleGatorFaceRegionLayout):
                if region.face_metadata is not None:
                    name = region.face_metadata.identity_name
                    if name is not None:
                        db_entities = self.db_api_service.search_entities(query=name)["items"]

                        if len(db_entities) > 1:
                            caption = None
                            if isinstance(region.source_region, AnnoPageRegionLayout) and region.source_region.graphical_metadata is not None:
                                caption = region.source_region.graphical_metadata.title

                            db_entities = self.match_entity(name, caption, db_entities)

                        if len(db_entities) == 1:
                            region.face_metadata.page_identity.identity.peoplegator_id = db_entities[0]["entity_id"]
                            logger.info(f"Matched entity for name '{name}' with ID {db_entities[0]['entity_id']}.")

                        elif len(db_entities) == 0:
                            peoplegator_id = self.db_api_service.create_entity(name=name)["entity_id"]
                            region.face_metadata.page_identity.identity.peoplegator_id = peoplegator_id
                            logger.info(f"Created new entity for name '{name}' with ID {peoplegator_id}.")

                        else:
                            region.face_metadata.page_identity.identity.peoplegator_id = None
                            logger.warning(f"Multiple entities found for name '{name}' in region {region.id}. Skipping entity matching for this region.")

        return page_layout

    def match_entity(self, name, caption, db_entities):
        entities = self.prepare_entities(db_entities)
        result, messages = self.llm_prompter(data={
                                                 "name": name,
                                                 "context": caption,
                                                 "entities": entities
                                             },
                                             response_model=EntityMatchingResult)

        entities = self.postprocess_entities(entities, result)
        return entities

    @staticmethod
    def prepare_entities(db_entities):
        entities = []
        for i, entity in enumerate(db_entities):
            entities.append({
                "item_id": i,
                **entity
            })

        return entities

    @staticmethod
    def postprocess_entities(entities, result: EntityMatchingResult):
        if result.item_id is not None and result.name is not None:
            for entity in entities:
                if entity["item_id"] == result.item_id and entity["name"] == result.name:
                    return [entity]
        return []
