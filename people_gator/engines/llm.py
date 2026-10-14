import cv2
import json
import base64
import logging
import numpy as np
import multiprocessing

from typing import Any
from openai import OpenAI
from jinja2 import Template
from functools import partial
from jsonschema import validate, ValidationError

from people_gator.engines import BaseEngine
from people_gator.core.utils import compose_path


logger = logging.getLogger(__name__)


class LLMPrompter:
    def __init__(self, 
                 api_url: str, 
                 api_key: str, 
                 model_name: str,
                 reasoning_effort: str = "low",
                 max_output_tokens: int = 1000,
                 prompt_template_system: str|None = None, 
                 prompt_template_user: str|None = None,
                 json_schema = None,
                 max_attempts: int = 3,
                 num_processes: int = 4):
        self.api_url = api_url
        self.api_key = api_key
        self.model_name = model_name
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.prompt_template_system = Template(prompt_template_system) if prompt_template_system else None
        self.prompt_template_user = Template(prompt_template_user) if prompt_template_user else None
        self.json_schema = json_schema
        self.max_attempts = max_attempts
        self.num_processes = num_processes

    def __call__(self, data: dict, images: list|dict|None = None, response_model=None):
        return self.process(data, images, response_model)

    def process_parallel(self, data_list: list[dict], images_list: list[list|dict|None]|None = None, response_model=None):
        if images_list is None:
            images_list = [None] * len(data_list)

        request_args = [self._prepare_request_args(data, images, response_model) for data, images in zip(data_list, images_list)]

        with multiprocessing.Pool(processes=self.num_processes) as pool:
            results = pool.starmap(self._send_request, [(self.api_url, self.api_key, args, self.max_attempts, self.json_schema, response_model) for args in request_args])

        return results

    def process(self, data: dict, images: list|dict|None = None, response_model=None):
        request_args = self._prepare_request_args(data, images, response_model)
        result = self._send_request(self.api_url, self.api_key, request_args, self.max_attempts, self.json_schema, response_model)

        return result

    @staticmethod
    def _send_request(api_url, api_key, request_args: dict, max_attempts: int, json_schema, response_model=None):
        result = None
        client = OpenAI(base_url=api_url, api_key=api_key)

        for attempt in range(max_attempts):
            try:
                response = client.responses.create(**request_args)
                parsed_json = json.loads(strip_markdown(response.output_text))

                result = parsed_json

                if response_model:
                    result = response_model.model_validate(parsed_json)
                elif json_schema:
                    validate(instance=parsed_json, schema=json_schema)

            except ValidationError as e:
                logger.error(f"Attempt {attempt + 1} failed to validate JSON response: {e}")
                continue

            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed to get a valid response: {e}")
                continue

            if result:
                break

        return result

    def _prepare_request_args(self, data: dict, images: list|dict|None = None, response_model=None):
        messages = []

        if self.prompt_template_system:
            system_prompt = self.eval_prompt_template(self.prompt_template_system, data)
            messages.append({"role": "system", "content": [{"type": "input_text", "text": system_prompt}]})

        if self.prompt_template_user:
            user_prompt = self.eval_prompt_template(self.prompt_template_user, data)
            messages.append({"role": "user", "content": [{"type": "input_text", "text": user_prompt}]})

        if images is not None:
            if isinstance(images, dict):
                for key, image in images.items():
                    if type(image) == np.ndarray:
                        image = encode_image_to_base64(image)

                    messages.append({"role": "user", "content": [{"type": "input_text", "text": key}, {"type": "input_image", "image_url": image}]})

            else:
                for image in images:
                    if type(image) == np.ndarray:
                        image = encode_image_to_base64(image)

                    messages[-1]["content"].append({"type": "input_image", "image_url": image})

        request_args: dict[str, Any]  = {
            "model": self.model_name,
            "input": messages,
            "reasoning": {"effort": self.reasoning_effort},
            "max_output_tokens": self.max_output_tokens
        }

        output_schema = None
        schema_name = None

        if response_model is not None:
            output_schema = response_model.model_json_schema()
            schema_name = response_model.__name__

        elif self.json_schema is not None:
            output_schema = self.json_schema
            schema_name = "response"

        if output_schema is not None:
            request_args["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": output_schema,
                    "strict": True,
                }
            }

        return request_args

    def eval_prompt_template(self, template: Template, data: dict):
        return template.render(**data)



class LLMBasedEngine(BaseEngine):
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
        self.reasoning_effort = self.config.get("reasoning_effort", "low")
        self.max_output_tokens = self.config.getint("max_output_tokens", 1000)

        self.llm_prompter = LLMPrompter(
            api_url=self.api_url,
            api_key=self.api_key,
            model_name=self.model_name,
            reasoning_effort=self.reasoning_effort,
            max_output_tokens=self.max_output_tokens,
            prompt_template_system=self.prompt_template_system,
            prompt_template_user=self.prompt_template_user,
            json_schema=self.json_schema
        )

    def load_prompt_template(self):
        if self.prompt_template_path:
            prompt_template_path = compose_path(self.prompt_template_path, self.config_path)
            with open(prompt_template_path, "r") as f:
                prompt_template = json.load(f)

            if "system" in prompt_template:
                self.prompt_template_system = prompt_template["system"]

            if "user" in prompt_template:
                self.prompt_template_user = prompt_template["user"]

    def load_json_schema(self):
        if self.json_schema_path:
            json_schema_path = compose_path(self.json_schema_path, self.config_path)
            with open(json_schema_path, "r") as f:
                self.json_schema = json.load(f)


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
