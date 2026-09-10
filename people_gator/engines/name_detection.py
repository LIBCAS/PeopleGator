from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine, PageProcessingEngine
from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout


class LLMNameDetectionEngine(DocumentProcessingEngine, PageProcessingEngine, LLMBasedEngine):
    def __init__(self, config, device, config_path):
        super().__init__(config, device, config_path)

    def process_document(self, document: PeopleGatorDocument):
        document.page_layouts = [self.process_page(None, page_layout) for page_layout in document.page_layouts]
        return document
        
    def process_page(self, page_image, page_layout: PeopleGatorPageLayout):                
        data = self.prepare_data(page_layout)
        result = self.llm_prompter(data)
        page_layout = self.update_page_layout(page_layout, result)
        return page_layout

    def prepare_data(self, page_layout: PeopleGatorPageLayout):
        data = {
            "lines": [line.transcription for line in page_layout.lines_iterator()],
        }
        return data

    def update_page_layout(self, page_layout: PeopleGatorPageLayout, result):
        raise NotImplementedError("Not implemented yet.")
