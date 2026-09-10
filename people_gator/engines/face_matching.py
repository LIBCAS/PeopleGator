from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine
from people_gator.core.layout import PeopleGatorDocument


class FaceMatchingEngine(DocumentProcessingEngine, LLMBasedEngine):
    def __init__(self, config, device, config_path):
        super().__init__(config, device, config_path)

    def process_document(self, document: PeopleGatorDocument):
        faces, face_images = self.prepare_faces(document)
        text_entities = self.prepare_text_entities(document.text_entities)
        result = self.llm_prompter(text_entities, face_images)
        self.update_document(document, faces, result)
        return document

    def prepare_text_entities(self, text_entities):
        raise NotImplementedError("Not implemented yet.")

    def prepare_faces(self, document):
        raise NotImplementedError("Not implemented yet.")

    def update_document(self, document, faces, result):
        raise NotImplementedError("Not implemented yet.")
