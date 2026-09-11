import logging

from pydantic import BaseModel, ConfigDict, Field

from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine, PageProcessingEngine
from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout, PeopleGatorTextEntity


logger = logging.getLogger(__name__)


class PersonName(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_name: str = Field(description="Normalized form of the person's name.")
    name_in_text: str = Field(description="The person's name exactly as it appears in the OCR transcription.")
    line: int = Field(ge=1, description="Line number on which the name occurs.")


class PersonExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    people: list[PersonName]


class LLMNameDetectionEngine(DocumentProcessingEngine, PageProcessingEngine, LLMBasedEngine):
    def __init__(self, config, device, config_path):
        super().__init__(config, device, config_path)

    def process_document(self, document: PeopleGatorDocument):
        document.page_layouts = [self.process_page(None, page_layout) for page_layout in document.page_layouts]
        return document
        
    def process_page(self, page_image, page_layout: PeopleGatorPageLayout):                
        data = self.prepare_data(page_layout)
        result: PersonExtraction = self.llm_prompter(data, response_model=PersonExtraction)
        page_layout = self.update_page_layout(page_layout, result)
        return page_layout

    def prepare_data(self, page_layout: PeopleGatorPageLayout):
        data = {
            "lines": [{"transcription": line.transcription.strip()} for line in page_layout.lines_iterator()]
        }
        return data

    def update_page_layout(self, page_layout: PeopleGatorPageLayout, result: PersonExtraction):
        lines = list(page_layout.lines_iterator())
        for person in result.people:
            line_index = person.line - 1
            if 0 <= line_index < len(lines):
                line = lines[line_index]

                if person.name_in_text in line.transcription:
                    start_index = line.transcription.index(person.name_in_text)
                    end_index = start_index + len(person.name_in_text)
                    page_layout.text_entities.append(PeopleGatorTextEntity(
                        name=person.normalized_name,
                        text=person.name_in_text,
                        line=line,
                        span=(start_index, end_index)
                    ))
                else:
                    logger.warning(f"Name '{person.name_in_text}' not found in line transcription '{line.transcription}'")
            else:
                logger.warning(f"Line number {person.line} is out of range for page layout with {len(lines)} lines.")
