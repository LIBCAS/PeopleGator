import os
import cv2
import torch
import logging
import argparse
import configparser

from safe_gpu import safe_gpu

from people_gator.core.layout import PeopleGatorDocument, render_to_image
from people_gator.core.document_parser import DocumentParser


def parse_arguments():
    """Parse this command's arguments from the process command line.

    Returns:
        An argparse.Namespace with the parsed command options.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Path to config file.", required=True)
    parser.add_argument("--input-image-path", help="Path to directory with images to process.")
    parser.add_argument("--input-metadata-path", help="Path to a metadata file.")

    group1 = parser.add_mutually_exclusive_group()
    group1.add_argument("--input-xml-path", help="Path to directory with PAGE XML files", required=False, default=None)
    group1.add_argument("--input-alto-path", help="Path to directory with ALTO XML files", required=False, default=None)

    parser.add_argument("--output-xml-path", help="Path to directory where PAGE XML files will be saved.")
    parser.add_argument("--output-alto-path", help="Path to directory where ALTO files will be saved.")
    parser.add_argument("--output-render-path", help="Path to directory where rendered images will be saved.")
    parser.add_argument("--processing-checkpoints", help="Directory for private per-engine JSON metadata + Pickle checkpoints (empty disables).")
    parser.add_argument("--resume-from-checkpoint", help="Continue from a trusted local checkpoint directory or checkpoint.json using the supplied configuration.")

    parser.add_argument("--import-from-app", action="store_true", help="Import the document from the People Gator app instead of processing it locally.")
    parser.add_argument("--export-to-app", action="store_true", help="Export the processed document to the People Gator app.")
    parser.add_argument("--drop-existing-annotations", action="store_true", help="Drop existing annotations in the document before exporting.")

    parser.add_argument("--device", choices=["gpu", "cpu"], default="cpu", help="Device to use for processing (default: cpu).")
    parser.add_argument("--gpu-id", type=int, default=None, help="GPU index to use (if device is gpu).")

    parser.add_argument("--logging-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="Logging level (default: INFO).")

    args = parser.parse_args()
    return args


def setup_logging(logging_level):
    """Set the root logging level and format, adding handlers only when needed.

    Args:
        logging_level: Root logging level name accepted by the CLI.
    """
    level = logging.getLevelName(logging_level)

    log_formatter = logging.Formatter('[%(levelname)s|%(asctime)s|%(filename)s:%(name)s]: %(message)s', datefmt="%Y-%m-%d_%H-%M-%S")

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not root_logger.handlers:
        root_logger.addHandler(logging.StreamHandler())

    root_handler = root_logger.handlers[0]
    root_handler.setFormatter(log_formatter)

    root_logger.info("Logging initialized")


def get_device(device, gpu_index=None, logger=None):
    """Select a torch device, claiming GPUs when no explicit GPU index is supplied.

    Args:
        device: Processing device (torch device or cpu/gpu selection).
        gpu_index: Optional explicit CUDA index; overrides automatic device selection.
        logger: Optional logger passed to GPU allocation.

    Returns:
        The selected torch.device.
    """
    if gpu_index is None:
        if device == "gpu":
            safe_gpu.claim_gpus(logger=logger)
            torch_device = torch.device("cuda")
        else:
            torch_device = torch.device("cpu")
    else:
        torch_device = torch.device(f"cuda:{gpu_index}")

    return torch_device


def get_value_or_none(config, section, key, getboolean: bool = False):
    """Return an INI value, optionally parsed as a boolean, or None if absent.

    Args:
        config: INI configuration or engine section for this component.
        section: INI section name.
        key: Configuration key or landmark label for this operation.
        getboolean: Whether to parse the value as a boolean; defaults to False.
    """
    if config.has_option(section, key):
        if getboolean:
            value = config.getboolean(section, key)
        else:
            value = config[section][key]
    else:
        value = None
    return value


def load_config(config_path):
    """Read an INI file and return its ConfigParser.

    Args:
        config_path: Path to the INI configuration file to read.
    """
    logging.getLogger(__name__).debug("Loading processing configuration")
    config = configparser.ConfigParser()
    config.read(config_path)
    return config


def create_document_parser(config, device, config_path):
    """Create the configured document-processing pipeline.

    Args:
        config: INI configuration or engine section for this component.
        device: Processing device (torch device or cpu/gpu selection).
        config_path: Base directory for relative engine resource paths.

    Returns:
        A parser with engines in configuration section order.
    """
    document_parser = DocumentParser(config, device, config_path)
    return document_parser


def load_document(input_images_path, input_xml_path=None, input_alto_path=None, input_metadata_path=None):
    """Construct a document from images, optional XML layouts, and metadata.

    Args:
        input_images_path: Input directory containing page JPEGs.
        input_xml_path: Optional PAGE XML directory.
        input_alto_path: Optional ALTO XML directory.
        input_metadata_path: Optional document/page metadata JSON path.

    Returns:
        A document with the supplied inputs loaded according to its defaults.
    """
    document = PeopleGatorDocument(page_images_dir=input_images_path, page_xmls_dir=input_xml_path, alto_xmls_dir=input_alto_path, metadata_path=input_metadata_path)
    return document


def main():
    """Process configured input pages and write the requested outputs.

    Returns:
        Zero after the command completes normally.
    """
    args = parse_arguments()
    config_path = args.config

    setup_logging(args.logging_level)
    logger = logging.getLogger(__name__)

    logger.debug("Processing CLI initialized on device %s", args.device)

    if not os.path.isfile(config_path):
        logger.error("Config file does not exist: '%s'.", config_path)
        exit(-1)

    config = load_config(args.config)

    if 'PARSE_FOLDER' not in config:
        config.add_section('PARSE_FOLDER')

    if args.input_image_path is not None:
        config['PARSE_FOLDER']['INPUT_IMAGE_PATH'] = args.input_image_path

    if args.input_xml_path is not None:
        config['PARSE_FOLDER']['INPUT_XML_PATH'] = args.input_xml_path

    if args.input_alto_path is not None:
        config['PARSE_FOLDER']['INPUT_ALTO_PATH'] = args.input_alto_path

    if args.input_metadata_path is not None:
        config['PARSE_FOLDER']['INPUT_METADATA_PATH'] = args.input_metadata_path

    if args.output_xml_path is not None:
        config['PARSE_FOLDER']['OUTPUT_XML_PATH'] = args.output_xml_path

    if args.output_alto_path is not None:
        config['PARSE_FOLDER']['OUTPUT_ALTO_PATH'] = args.output_alto_path

    if args.output_render_path is not None:
        config['PARSE_FOLDER']['OUTPUT_RENDER_PATH'] = args.output_render_path

    if args.processing_checkpoints is not None:
        config['PARSE_FOLDER']['PROCESSING_CHECKPOINTS'] = args.processing_checkpoints

    if args.import_from_app:
        config['PARSE_FOLDER']['IMPORT_FROM_APP'] = 'yes'

    if args.export_to_app:
        config['PARSE_FOLDER']['EXPORT_TO_APP'] = 'yes'

    if args.drop_existing_annotations:
        config['PARSE_FOLDER']['DROP_EXISTING_ANNOTATIONS'] = 'yes'

    device = get_device(args.device, args.gpu_id, logger)

    config_dir = os.path.dirname(config_path)

    document_parser = create_document_parser(config, device, config_path=config_dir)

    input_image_path = get_value_or_none(config, 'PARSE_FOLDER', 'INPUT_IMAGE_PATH')
    input_xml_path = get_value_or_none(config, 'PARSE_FOLDER', 'INPUT_XML_PATH')
    input_alto_path = get_value_or_none(config, 'PARSE_FOLDER', 'INPUT_ALTO_PATH')
    input_metadata_path = get_value_or_none(config, 'PARSE_FOLDER', 'INPUT_METADATA_PATH')
    output_xml_path = get_value_or_none(config, 'PARSE_FOLDER', 'OUTPUT_XML_PATH')
    output_alto_path = get_value_or_none(config, 'PARSE_FOLDER', 'OUTPUT_ALTO_PATH')
    output_render_path = get_value_or_none(config, 'PARSE_FOLDER', 'OUTPUT_RENDER_PATH')

    import_from_app = get_value_or_none(config, 'PARSE_FOLDER', 'IMPORT_FROM_APP', getboolean=True)
    export_to_app = get_value_or_none(config, 'PARSE_FOLDER', 'EXPORT_TO_APP', getboolean=True)
    drop_existing_annotations = get_value_or_none(config, 'PARSE_FOLDER', 'DROP_EXISTING_ANNOTATIONS', getboolean=True)

    if import_from_app is None:
        import_from_app = False

    if export_to_app is None:
        export_to_app = False

    if drop_existing_annotations is None:
        drop_existing_annotations = False

    document = None if args.resume_from_checkpoint else load_document(input_images_path=input_image_path,
                             input_xml_path=input_xml_path,
                             input_alto_path=input_alto_path,
                             input_metadata_path=input_metadata_path)

    processing_options = dict(import_from_app=import_from_app, export_to_app=export_to_app,
                              drop_existing_annotations=drop_existing_annotations)
    if args.resume_from_checkpoint:
        processing_options['resume_from_checkpoint'] = args.resume_from_checkpoint
    document = document_parser.process_document(document, **processing_options)


    if output_xml_path and not os.path.exists(output_xml_path):
        os.makedirs(output_xml_path)

    if output_alto_path and not os.path.exists(output_alto_path):
        os.makedirs(output_alto_path)

    if output_xml_path:
        logger.info("Writing PAGE XML output")
        document.to_pagexml(output_xml_path)

    if output_alto_path:
        logger.info("Writing ALTO XML output")
        document.to_altoxml(output_alto_path)

    if output_render_path:
        if not os.path.exists(output_render_path):
            os.makedirs(output_render_path)

        for page_image, page_layout in document.pages_iterator():
            rendered_image = render_to_image(page_image, page_layout)
            output_image_path = os.path.join(output_render_path, f"{page_layout.id}.jpg")
            cv2.imwrite(output_image_path, rendered_image)
            logger.debug("Rendered page %s", page_layout.id)

    logger.info("Processing completed successfully.")

    return 0


if __name__ == "__main__":
    exit(main())
