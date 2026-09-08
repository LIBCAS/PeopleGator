import json

from people_gator.engines import DocumentProcessingEngine, PageProcessingEngine, LLMPrompter
from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout


class NameDetectionEngine(DocumentProcessingEngine, PageProcessingEngine):
    def __init__(self, config, device, config_path):
        super().__init__(config, device, config_path)

        self.prompt_template_path = self.config.get("prompt_template_path")
        self.json_schema_path = self.config.get("json_schema_path")

        self.prompt_template_system = None
        self.prompt_template_user = None
        self.json_schema = None

        self.load_prompt_template()
        self.load_json_schema()

        self.api_url = self.config.get("api_url")
        self.api_key = self.config.get("api_key")
        self.model_name = self.config.get("model_name")

        self.llm_prompter = LLMPrompter(
            api_url=self.api_url,
            api_key=self.api_key,
            model_name=self.model_name,
            prompt_template_system=self.prompt_template_system,
            prompt_template_user=self.prompt_template_user,
            json_schema=self.json_schema
        )

    def load_prompt_template(self):
        if self.prompt_template_path:
            with open(self.prompt_template_path, "r") as f:
                prompt_template = json.load(f)

            if "system" in prompt_template:
                self.prompt_template_system = prompt_template["system"]

            if "user" in prompt_template:
                self.prompt_template_user = prompt_template["user"]

    def load_json_schema(self):
        if self.json_schema_path:
            with open(self.json_schema_path, "r") as f:
                self.json_schema = json.load(f)

    def process_document(self, document: PeopleGatorDocument):
        document.page_layouts = [self.process_page(None, page_layout) for page_layout in document.page_layouts]
        return document
        
    def process_page(self, page_image, page_layout: PeopleGatorPageLayout):                
        data = self.prepare_data(page_layout)
        result = self.llm_prompter.prompt(data)
        page_layout = self.update_page_layout(page_layout, result)
        return page_layout

    def prepare_data(self, page_layout: PeopleGatorPageLayout):
        data = {
            "lines": [line.transcription for line in page_layout.lines_iterator()],
        }
        return data

    def update_page_layout(self, page_layout: PeopleGatorPageLayout, result):
        # TODO: Implement the logic to update the page_layout based on the result from the LLM prompter
        return page_layout
