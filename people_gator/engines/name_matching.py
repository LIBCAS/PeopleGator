from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine
from people_gator.core.layout import PeopleGatorDocument


class LLMNameMatchingEngine(DocumentProcessingEngine, LLMBasedEngine):
    def __init__(self, config, device, config_path):
        super().__init__(config, device, config_path)

    def process_document(self, document: PeopleGatorDocument):
        raise NotImplementedError("Not implemented yet.")
