import logging
import argparse

from doc_api.adapter import Adapter
from doc_api.connector import Connector
from doc_api.api.schemas.base_objects import Engine
from doc_client.doc_client_wrapper import DocClientWrapper


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--api-url", type=str, help="URL of the API endpoint.", required=True)
    parser.add_argument("--api-key", type=str, help="API key for authentication.", required=True)

    group1 = parser.add_mutually_exclusive_group(required=True)
    group1.add_argument("--list-engines", action="store_true", help="List available engines and exit.")

    group1.add_argument("--images", type=str, help="Path to directory with images.")

    parser.add_argument("--metadata", type=str, help="Path to the metadata JSON.", required=False, default=None)
    parser.add_argument("--engine-name", type=str, help="Name of the processing engine to use.", required=False, default=None)
    parser.add_argument("--output", type=str, help="Path to the output dir.", required=False, default="./")

    group2 = parser.add_mutually_exclusive_group(required=False)
    group2.add_argument("--alto-xmls", type=str, help="Path to directory with ALTO XMLs.", required=False, default=None)
    group2.add_argument("--page-xmls", type=str, help="Path to directory with PAGE XMLs.", required=False, default=None)

    parser.add_argument("--polling-interval", help="Time in seconds to wait between result checks.", required=False, default=1.0, type=float)
    parser.add_argument("--logging-level", help="Logging level.", required=False, type=str, choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], default="INFO")

    args = parser.parse_args()
    return args


class PeopleGatorClient(DocClientWrapper):
    pass


def setup_logging(logging_level):
    level = logging.getLevelName(logging_level)

    console_log_formatter = logging.Formatter('%(message)s')

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        root_logger.addHandler(console_handler)

    root_handler = root_logger.handlers[0]
    root_handler.setFormatter(console_log_formatter)


def format_engines(engines: list[Engine]) -> str:
    if not engines:
        return "No available engines."

    lines = ["Available engines:", ""]
    for engine in engines:
        lines.append(f"Name: '{engine.name}'")

        if len(engine.description) > 80 or "\n" in engine.description:
            lines.append("Description:")
            lines.append(engine.description)
        else:
            lines.append(f"Description: {engine.description}")

        lines.append("")

    output = "\n".join(lines).strip()
    return output


def main():
    args = parse_args()

    setup_logging(args.logging_level)
    logger = logging.getLogger(__name__)

    connector = Connector(args.api_key, user_agent="AnnoPageClient/1.0")

    if args.list_engines:
        adapter = Adapter(args.api_url, connector)
        engines = adapter.get_engines()
        if engines.data:
            output = format_engines(engines.data)
            logger.info(output)
        else:
            logger.info("No available engines.")

    else:
        client = PeopleGatorClient(api_url=args.api_url,
                                   connector=connector,
                                   polling_interval=args.polling_interval)

        client.run_job_pipeline(
            images_dir=args.images,
            result_dir=args.output,
            alto_dir=args.alto_xmls,
            page_xml_dir=args.page_xmls,
            meta_file=args.metadata,
            engine_name=args.engine_name,
        )

    return 0


if __name__ == "__main__":
    exit(main())
