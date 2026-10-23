import json
import logging
import argparse
import configparser

from pydantic import BaseModel, ConfigDict, Field, model_validator

from people_gator.core.db import DatabaseApiService
from people_gator.engines.llm import LLMPrompter


class EntityGroup(BaseModel):
    """A group of entity occurrences referring to the same person."""

    model_config = ConfigDict(extra="forbid")

    entity_ids: list[int] = Field(
        description=(
            "IDs of entity occurrences referring to the same person. "
            "Must contain at least two unique entity IDs."
        )
    )

    name: str = Field(
        description=(
            "The canonical name of the person, consolidated from "
            "the names of all merged entities."
        )
    )

    short_description: str = Field(
        description=(
            "A concise, unified description of the person, combining "
            "the most relevant identifying information."
        )
    )

    long_description: str = Field(
        description=(
            "A comprehensive, coherent description of the person, "
            "preserving all relevant, non-contradictory information "
            "from the merged entities without introducing new facts."
        )
    )

    @model_validator(mode="after")
    def validate_entity_ids(self):
        if len(self.entity_ids) < 2:
            raise ValueError("Each group must contain at least two entities.")

        if len(self.entity_ids) != len(set(self.entity_ids)):
            raise ValueError("Entity IDs within a group must be unique.")

        return self


class EntityResolutionOutput(BaseModel):
    """Result of resolving and consolidating person entities."""

    model_config = ConfigDict(extra="forbid")

    groups: list[EntityGroup] = Field(
        description=(
            "Groups of entity occurrences referring to the same "
            "individual, including their consolidated information. "
            "Entities without a confident match are omitted."
        )
    )

    @model_validator(mode="after")
    def validate_unique_entities(self):
        all_ids = [
            entity_id
            for group in self.groups
            for entity_id in group.entity_ids
        ]

        if len(all_ids) != len(set(all_ids)):
            raise ValueError(
                "Each entity ID may appear in at most one group."
            )

        return self



def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Path to the configuration INI file with DB_API settings.")
    parser.add_argument("--metadata", help="Path to the document metadata JSON file.")
    parser.add_argument("--prompt", help="Path to the prompt file.")

    parser.add_argument("--api-url", help="URL of the LLM API.")
    parser.add_argument("--api-key", help="API key for the LLM API.")
    parser.add_argument("--model", help="Name of the LLM model to use.")
    parser.add_argument("--reasoning-effort", choices=["low", "medium", "high"], default="low", help="Reasoning effort level for the LLM (default: low).")
    parser.add_argument("--max-output-tokens", type=int, default=1000, help="Maximum number of output tokens for the LLM (default: 1000).")

    parser.add_argument("--logging-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="Logging level (default: INFO).")

    args = parser.parse_args()
    return args


def setup_logging(logging_level):
    level = logging.getLevelName(logging_level)

    log_formatter = logging.Formatter('[%(levelname)s|%(asctime)s|%(filename)s:%(name)s]: %(message)s', datefmt="%Y-%m-%d_%H-%M-%S")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    root_handler = root_logger.handlers[0]
    root_handler.setFormatter(log_formatter)

    root_logger.info("Logging initialized")


def load_config(config_path):
    config = configparser.ConfigParser()
    config.read(config_path)
    return config


def load_metadata(metadata_path):
    with open(metadata_path, "r") as f:
        metadata = json.load(f)
    return metadata


def load_prompt(prompt_path):
    with open(prompt_path, "r") as f:
        prompt = json.load(f)
    return prompt


def evaluate_page_entities(llm_prompter: LLMPrompter, db_page_entities):
    data = []
    for i, entity in enumerate(db_page_entities["items"]):
        data.append({
            "id": i,
            "name": entity["name"],
            "short_description": entity["short_description"],
            "long_description": entity["description"]
        })

    output = llm_prompter.process({"entities": data}, response_model=EntityResolutionOutput)
    return output


def main():
    args = parse_arguments()

    config = load_config(args.config)
    prompt = load_prompt(args.prompt)
    db_api_service = DatabaseApiService(config["DB_API"])

    llm_prompter = LLMPrompter(
        api_url=args.api_url,
        api_key=args.api_key,
        model_name=args.model,
        reasoning_effort=args.reasoning_effort,
        max_output_tokens=args.max_output_tokens,
        prompt_template_system=prompt["system"],
        prompt_template_user=prompt["user"]
    )


    metadata = load_metadata(args.metadata)
    document_id = metadata["document"]["id"]
    document_name = metadata["document"]["name"]
    library = metadata["document"]["library"]

    db_pages = db_api_service.get_document_pages(document_id, library)
    for db_page in db_pages["items"]:
        db_page_source_id = db_page["source_id"]
        print(f"Processing page {db_page_source_id} of document '{document_name}' (ID: {document_id}) in library '{library}'")

        db_page_entities = db_api_service.get_entities_for_page(db_page_source_id)
        result = evaluate_page_entities(llm_prompter, db_page_entities)
        for group in result.groups:
            entities = [db_page_entities["items"][i] for i in group.entity_ids]
            target_entity_id = entities[0]["entity_id"]
            other_entity_ids = [entity["entity_id"] for entity in entities[1:]]

            print(f"Merging entities {other_entity_ids} into target entity {target_entity_id} for page {db_page_source_id}")

            db_api_service.merge_entities(target_entity_id, other_entity_ids, description=group.long_description, short_description=group.short_description)

    return 0


if __name__ == "__main__":
    exit(main())
