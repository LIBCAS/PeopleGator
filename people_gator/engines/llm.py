import cv2
import json
import base64
import logging
import numpy as np
import multiprocessing

from typing import Any
from openai import OpenAI
from jinja2 import Template, TemplateError, meta
from functools import partial
from jsonschema import validate, ValidationError
from pydantic import ValidationError as PydanticValidationError

from people_gator.engines import BaseEngine
from people_gator.core.utils import compose_path


logger = logging.getLogger(__name__)


class LLMPromptConfigurationError(ValueError):
    """Safe, actionable prompt-file configuration error for every LLM engine."""


class LLMRequestError(RuntimeError):
    """Request transport, incomplete output or request exhaustion failed safely."""


class LLMResponseError(ValueError):
    """A completed provider response contained unusable structured content."""


class LLMPrompter:
    """Render prompts and request structured LLM responses with bounded retries."""

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
                 num_processes: int = 4,
                 raise_on_failure: bool = False):
        """Configure prompt rendering, response validation, and LLM request limits.

        Args:
            api_url: Service base URL.
            api_key: Service authentication key.
            model_name: LLM model identifier.
            reasoning_effort: Requested reasoning effort; defaults to low.
            max_output_tokens: Response token limit; defaults to 1000.
            prompt_template_system: Optional Jinja2 system-prompt source.
            prompt_template_user: Optional Jinja2 user-prompt source.
            json_schema: Optional output schema used when no response model is supplied.
            max_attempts: Maximum request attempts; defaults to 3.
            num_processes: Parallel request pool size; defaults to 4.
            raise_on_failure: Raise safe request/content errors after retries; defaults to False.
        """
        self.api_url = api_url
        self.api_key = api_key
        self.model_name = model_name
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.prompt_template_system = Template(prompt_template_system) if prompt_template_system else None
        self.prompt_template_user = Template(prompt_template_user) if prompt_template_user else None
        self._template_variables = set()
        for source, template in ((prompt_template_system, self.prompt_template_system),
                                 (prompt_template_user, self.prompt_template_user)):
            if template is not None:
                self._template_variables.update(meta.find_undeclared_variables(template.environment.parse(source)))
        self.json_schema = json_schema
        self.max_attempts = max_attempts
        self.num_processes = num_processes
        self.raise_on_failure = raise_on_failure

    def __call__(self, data: dict, images: list|dict|None = None, response_model=None, interactions=None):
        """Delegate to the primary operation with the supplied arguments.

        Args:
            data: Template context mapping.
            images: Optional images as an ordered list or label-to-image mapping.
            response_model: Optional Pydantic response class; None returns decoded JSON.
            interactions: Optional caller-owned output list; existing entries are preserved.

        Returns:
            The result of the delegated operation.
        """
        return self.process(data, images, response_model, interactions=interactions)

    def process_parallel(self, data_list: list[dict], images_list: list[list|dict|None]|None = None, response_model=None, interactions=None):
        """Return LLM results in request order using a multiprocessing pool.

        Args:
            data_list: Prompt-context dictionaries in request order.
            images_list: Optional per-request images; None supplies no images.
            response_model: Optional Pydantic response class; None returns decoded JSON.
            interactions: Optional output list receiving one attempt list per request,
                in input order; existing entries are preserved, including on request failure.
        """
        if images_list is None:
            images_list = [None] * len(data_list)

        logger.debug("Preparing %d parallel LLM requests with %d processes", len(data_list), self.num_processes)
        request_args = [self._prepare_request_args(data, images, response_model) for data, images in zip(data_list, images_list)]

        sender = self._send_request if interactions is None else self._send_request_with_interactions
        with multiprocessing.Pool(processes=self.num_processes) as pool:
            results = pool.starmap(sender, [(self.api_url, self.api_key, args, self.max_attempts, self.json_schema, response_model, self.raise_on_failure) for args in request_args])

        if interactions is not None:
            interactions.extend(records for _, records in results)
            results = [result for result, _ in results]
            for result in results:
                if isinstance(result, Exception):
                    raise result

        return results

    def process(self, data: dict, images: list|dict|None = None, response_model=None, interactions=None):
        """Render a prompt and return the structured LLM result.

        Args:
            data: Template context mapping.
            images: Optional images as an ordered list or label-to-image mapping.
            response_model: Optional Pydantic response class; None returns decoded JSON.
            interactions: Optional caller-owned output list; existing entries are preserved.

        Returns:
            The latest LLM result; see _send_request for failure semantics.
        """
        request_args = self._prepare_request_args(data, images, response_model)
        return self._send_request(
            self.api_url, self.api_key, request_args, self.max_attempts,
            self.json_schema, response_model, self.raise_on_failure, interactions=interactions)

    @staticmethod
    def _send_request_with_interactions(*args):
        """Return attempt records across a process boundary, retaining request errors.

        Args:
            *args: Positional arguments for the unchanged request operation.
        """
        records = []
        try:
            result = LLMPrompter._send_request(*args, interactions=records)
        except Exception as exc:
            result = exc
        return result, records

    @staticmethod
    def _send_request(api_url, api_key, request_args: dict, max_attempts: int, json_schema, response_model=None, raise_on_failure=False, interactions=None):
        """Request and validate an LLM response with bounded retries.

        Args:
            api_url: Service base URL.
            api_key: Service authentication key.
            request_args: Prepared Responses API keyword arguments.
            max_attempts: Maximum number of request attempts.
            json_schema: Output schema used when no response model is supplied; may be None.
            response_model: Optional Pydantic response class; None returns decoded JSON.
            raise_on_failure: Distinguish failed requests from invalid response content; defaults to False.
            interactions: Optional list receiving rendered text and raw output for each attempt.

        Returns:
            The latest decoded result, optionally validated, or None. A decoded
            value can survive a subsequent validation failure, as in existing callers.
            Only explicitly completed responses are parsed; other statuses are
            request failures and discard earlier unvalidated content.
            Incomplete output is rejected; an exhausted output allowance stops
            retries immediately without parsing or accepting a partial result.
            Opt-in raise_on_failure raises LLMRequestError or LLMResponseError
            instead of returning stale content from an unsuccessful last attempt.
        """
        logger.debug("Starting structured LLM request; maximum attempts=%d", max_attempts)
        result = None
        validated = False
        failure_type = LLMRequestError
        client = OpenAI(base_url=api_url, api_key=api_key)

        prompt = "\n".join(
            f"[{message['role']}]\n" + "\n".join(
                part['text'] for part in message['content'] if part['type'] == 'input_text')
            for message in request_args['input']
            if any(part['type'] == 'input_text' for part in message['content'])
        ) if interactions is not None else None
        for attempt in range(max_attempts):
            validated = False
            failure_type = LLMRequestError
            decode_stage = "HTTP response decoding"
            if interactions is not None:
                record = {'prompt': prompt, 'response': None}
                interactions.append(record)
            try:
                response = client.responses.create(**request_args)
                if interactions is not None:
                    record['response'] = getattr(response, 'output_text', None)
                status = getattr(response, "status", None)
                if status == "incomplete":
                    result = None
                    reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
                    if reason == "max_output_tokens":
                        logger.error("LLM response reached MAX_OUTPUT_TOKENS=%s before completing JSON; "
                                     "increase MAX_OUTPUT_TOKENS. "
                                     "The output allowance includes reasoning tokens. No identical retry will help.",
                                     request_args.get("max_output_tokens", "unknown"))
                        if raise_on_failure:
                            raise LLMRequestError('LLM output allowance exhausted')
                        return None
                    logger.warning("LLM attempt %d/%d returned an incomplete response; retrying",
                                   attempt + 1, max_attempts)
                    continue
                if status != "completed":
                    result = None
                    logger.warning("LLM attempt %d/%d returned a non-completed response; retrying",
                                   attempt + 1, max_attempts)
                    continue
                decode_stage = "model output decoding"
                output_text = response.output_text or ""
                logger.debug("LLM response: text characters=%d, output tokens=%s, reasoning tokens=%s",
                             len(output_text), getattr(getattr(response, "usage", None), "output_tokens", None),
                             getattr(getattr(getattr(response, "usage", None), "output_tokens_details", None),
                                     "reasoning_tokens", None))
                parsed_json = json.loads(strip_markdown(output_text))

                result = parsed_json

                if response_model:
                    result = response_model.model_validate(parsed_json)
                elif json_schema:
                    validate(instance=parsed_json, schema=json_schema)

            except LLMRequestError:
                raise

            except json.JSONDecodeError as e:
                failure_type = LLMResponseError if decode_stage == "model output decoding" else LLMRequestError
                logger.warning("LLM attempt %d/%d failed (JSONDecodeError) during %s at character %d",
                               attempt + 1, max_attempts, decode_stage, e.pos)
                continue

            except (ValidationError, PydanticValidationError) as e:
                failure_type = LLMResponseError
                logger.warning("LLM attempt %d/%d: response schema validation failed (%s)", attempt + 1, max_attempts, type(e).__name__)
                continue

            except Exception as e:
                logger.warning("LLM attempt %d/%d failed (%s)", attempt + 1, max_attempts, type(e).__name__)
                continue

            validated = True
            if result:
                break

        if not validated or not result:
            logger.error("LLM request exhausted %d attempts without a usable response", max_attempts)
            if raise_on_failure:
                raise failure_type("LLM request exhausted without a usable result")
        else:
            logger.debug("LLM request completed")
        return result

    def _prepare_request_args(self, data: dict, images: list|dict|None = None, response_model=None):
        """Build Responses API arguments from templates, images, and output schema.

        Args:
            data: Template context mapping.
            images: Optional images as an ordered list or label-to-image mapping.
            response_model: Optional Pydantic response class; None returns decoded JSON.

        Returns:
            Responses API keyword arguments with an optional output schema.
        """
        self._warn_template_data(data)
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

    def _warn_template_data(self, data: dict):
        """Warn once per mismatch against the union of both template roles.

        Args:
            data: Rendering mapping; only key names are logged, never values.
        """
        supplied = set(data)
        for name in sorted(self._template_variables - supplied):
            logger.warning("LLM template placeholder %s is missing from data", name)
        for name in sorted(supplied - self._template_variables, key=str):
            logger.warning("LLM data key %s is unused by system/user templates", name)

    def eval_prompt_template(self, template: Template, data: dict):
        """Return a Jinja2 template rendered with the supplied context.

        Args:
            template: Jinja2 template to render.
            data: Template context mapping.
        """
        return template.render(**data)



class LLMBasedEngine(BaseEngine):
    """Engine configuration for prompt templates, response schemas, and an LLM."""

    def __init__(self, config, device, config_path):
        """Initialize LLMBasedEngine from the supplied settings and data.

        Args:
            config: INI configuration or engine section for this component.
            device: Processing device (torch device or cpu/gpu selection).
            config_path: Base directory for relative engine resource paths.
        """
        super().__init__(config, device, config_path)

        self.prompt_template_path = self.config.get("prompt_template_path")
        self.json_schema_path = self.config.get("json_schema_path")

        self.prompt_template_system = None
        self.prompt_template_user = None
        self.json_schema = None

        logger.debug("Loading LLM prompt and response schema configuration")
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
        """Require readable prompt JSON with a usable system and/or user template.

        Raises:
            LLMPromptConfigurationError: If path, file, JSON structure, role types,
                content or Jinja2 syntax is invalid. Errors omit private paths
                and prompt contents. Validation precedes prompter construction.
        """
        if not isinstance(self.prompt_template_path, str) or not self.prompt_template_path.strip():
            raise LLMPromptConfigurationError(
                'LLM engines require PROMPT_TEMPLATE_PATH pointing to a readable prompt JSON '
                'object with nonblank system and/or user strings.')
        try:
            path = compose_path(self.prompt_template_path, self.config_path)
            with open(path, 'r', encoding='utf-8') as stream:
                prompt = json.load(stream)
        except (OSError, ValueError):
            raise LLMPromptConfigurationError(
                'Could not read valid prompt JSON; check PROMPT_TEMPLATE_PATH, file permissions '
                'and UTF-8 JSON syntax.') from None
        if not isinstance(prompt, dict):
            raise LLMPromptConfigurationError(
                'PROMPT_TEMPLATE_PATH must reference a JSON object with system/user templates.')
        templates = {}
        for role in ('system', 'user'):
            if role not in prompt:
                templates[role] = None
                continue
            value = prompt[role]
            if not isinstance(value, str):
                raise LLMPromptConfigurationError('Prompt JSON system/user values must be strings.')
            if not value.strip():
                templates[role] = None
                continue
            try:
                Template(value)
            except TemplateError:
                raise LLMPromptConfigurationError(
                    'Prompt JSON must contain valid Jinja2 system/user templates.') from None
            templates[role] = value
        if not any(templates.values()):
            raise LLMPromptConfigurationError(
                'Prompt JSON must contain a nonblank system and/or user string; '
                'check PROMPT_TEMPLATE_PATH.')
        self.prompt_template_system = templates['system']
        self.prompt_template_user = templates['user']

    def load_json_schema(self):
        """Load the optional response JSON schema when a path is present.

        Raises:
            OSError: If the configured resource cannot be read.
            ValueError: If the resource contains invalid JSON.
        """
        if self.json_schema_path:
            json_schema_path = compose_path(self.json_schema_path, self.config_path)
            with open(json_schema_path, "r") as f:
                self.json_schema = json.load(f)


def strip_markdown(text):
    """Return text without a complete outer JSON or unlabelled Markdown fence.

    Args:
        text: Source OCR text or input text for this operation.
    """
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
    """Return a JPEG data URL encoded from an OpenCV image.

    Args:
        image: OpenCV image array.
    """
    _, buffer = cv2.imencode('.jpg', image)
    image_base64 = base64.b64encode(buffer).decode("utf-8")
    return f"data:image/jpeg;base64,{image_base64}"
