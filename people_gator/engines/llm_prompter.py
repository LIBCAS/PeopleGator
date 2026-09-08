import cv2
import json
import base64
import logging
import numpy as np

from openai import OpenAI
from jinja2 import Template
from jsonschema import validate, ValidationError


logger = logging.getLogger(__name__)


class LLMPrompter:
    def __init__(self, 
                 api_url: str, 
                 api_key: str, 
                 model_name: str, 
                 prompt_template_system: str|None = None, 
                 prompt_template_user: str|None = None,
                 json_schema = None,
                 max_attempts: int = 3):
        self.client = OpenAI(api_key=api_key, api_base=api_url)
        self.model_name = model_name
        self.prompt_template_system = Template(prompt_template_system) if prompt_template_system else None
        self.prompt_template_user = Template(prompt_template_user) if prompt_template_user else None
        self.json_schema = json_schema
        self.max_attempts = max_attempts

    def __call__(self, data: dict, images: list):
        messages = []

        if self.prompt_template_system:
            system_prompt = self.eval_prompt_template(self.prompt_template_system, data)
            messages.append({"role": "system", "content": [{"type": "text", "text": system_prompt}]})

        if self.prompt_template_user:
            user_prompt = self.eval_prompt_template(self.prompt_template_user, data)
            messages.append({"role": "user", "content": [{"type": "text", "text": user_prompt}]})

        for image in images:
            if type(image) == np.ndarray:
                image = encode_image_to_base64(image)    

            messages[-1]["content"].append({"type": "image_url", "image_url": image})
            
        request_args = {
            "model": self.model_name,
            "input": messages,
        }

        result = None

        for attempt in range(self.max_attempts):
            try:
                response = self.client.responses.create(**request_args)
                parsed_json = json.loads(strip_markdown(response.output_text))
                if self.json_schema:
                    validate(instance=parsed_json, schema=self.json_schema)
                result = parsed_json

            except ValidationError as e:
                logger.error(f"Attempt {attempt + 1} failed to validate JSON response: {e}")
                continue

            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed to get a valid response: {e}")
                continue

            if result:
                break

        return result

    def eval_prompt_template(self, template: Template, data: dict):
        return template.render(**data)


def strip_markdown(text):
    text = (text or "").strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if len(lines) < 2 or not lines[-1].strip().startswith("```"):
        return text

    opening = lines[0].strip().lower()
    if opening not in ("```", "```json"):
        return text

    return "\n".join(lines[1:-1]).strip()


def encode_image_to_base64(image: np.ndarray) -> str:
    _, buffer = cv2.imencode('.jpg', image)
    image_base64 = base64.b64encode(buffer).decode("utf-8")
    return f"data:image/jpeg;base64,{image_base64}"
