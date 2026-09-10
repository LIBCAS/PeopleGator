from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine
from people_gator.core.layout import PeopleGatorDocument


class NameClusteringEngine(DocumentProcessingEngine):
    def __init__(self, config, device, config_path):
        super().__init__(config, device, config_path)

    def process_document(self, document: PeopleGatorDocument):
        text_entities = document.text_entities
        similarities = self.compute_similarities(text_entities)
        clusters = self.cluster_names(text_entities, similarities)
        document.text_entity_clusters = clusters
        return document

    def compute_similarities(self, text_entities):
        raise NotImplementedError("Not implemented yet.")

    def cluster_names(self, text_entities, similarities):
        raise NotImplementedError("Not implemented yet.")


class LLMNameClusteringCheckEngine(DocumentProcessingEngine, LLMBasedEngine):
    def __init__(self, config, device, config_path):
        super().__init__(config, device, config_path)

    def process_document(self, document: PeopleGatorDocument):
        clusters = document.text_entity_clusters
        data = self.prepare_data(clusters)
        check_result = self.llm_prompter(data)
        self.update_clusters(document, clusters, check_result)
        return document

    def prepare_data(self, clusters):
        raise NotImplementedError("Not implemented yet.")

    def update_clusters(self, document, clusters, check_result):
        raise NotImplementedError("Not implemented yet.")
