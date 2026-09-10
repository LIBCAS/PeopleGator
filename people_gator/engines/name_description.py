from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine
from people_gator.core.layout import PeopleGatorDocument


class LLMNameDescriptionEngine(DocumentProcessingEngine, LLMBasedEngine):
    def __init__(self, config, device, config_path):
        super().__init__(config, device, config_path)

    def process_document(self, document: PeopleGatorDocument):
        text_entities = document.text_entities
        data = self.prepare_data(text_entities)
        descriptions = self.llm_prompter(data)
        self.update_text_entities(document, text_entities, descriptions)
        return document

    def prepare_data(self, text_entities):
        raise NotImplementedError("Not implemented yet.")

    def update_text_entities(self, document, text_entities, descriptions):
        raise NotImplementedError("Not implemented yet.")
