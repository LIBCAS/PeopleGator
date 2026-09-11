import os
import torch
import argparse
import configparser

from safe_gpu import safe_gpu

from people_gator.core.layout import PeopleGatorDocument
from people_gator.core.document_parser import DocumentParser


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="Path to config file.", required=True)
    parser.add_argument("--input-image-path", help="Path to directory with images to process.")

    group1 = parser.add_mutually_exclusive_group()
    group1.add_argument("--input-xml-path", help="Path to directory with PAGE XML files", required=False, default=None)
    group1.add_argument("--input-alto-path", help="Path to directory with ALTO XML files", required=False, default=None)

    parser.add_argument("--output-xml-path", help="Path to directory where PAGE XML files will be saved.")
    parser.add_argument("--output-alto-path", help="Path to directory where ALTO files will be saved.")

    parser.add_argument("--device", choices=["gpu", "cpu"], default="cpu", help="Device to use for processing (default: cpu).")

    args = parser.parse_args()
    return args


def get_device(device, gpu_index=None, logger=None):
    if gpu_index is None:
        if device == "gpu":
            safe_gpu.claim_gpus(logger=logger)
            torch_device = torch.device("cuda")
        else:
            torch_device = torch.device("cpu")
    else:
        torch_device = torch.device(f"cuda:{gpu_index}")

    return torch_device


def load_config(config_path):
    config = configparser.ConfigParser()
    config.read(config_path)
    return config


def create_document_parser(config, device, config_path):
    document_parser = DocumentParser(config, device, config_path)
    return document_parser


def load_document(input_images_path, input_xml_path=None, input_alto_path=None):
    document = PeopleGatorDocument(page_images_dir=input_images_path)
    if input_alto_path:
        document.from_altoxml(input_alto_path)
    elif input_xml_path:
        document.from_pagexml(input_xml_path)
    return document


def main():
    args = parse_arguments()

    print("Starting processing with the following parameters:")
    print(f"Config file: {args.config}")
    print(f"Images directory: {args.input_image_path}")
    print(f"Input PAGE XML directory: {args.input_xml_path}")
    print(f"Input ALTO XML directory: {args.input_alto_path}")
    print(f"Output PAGE XML directory: {args.output_xml_path}")
    print(f"Output ALTO XML directory: {args.output_alto_path}")

    device = get_device(args.device)

    config = load_config(args.config)
    document_parser = create_document_parser(config, device, config_path=os.path.dirname(args.config))

    document = load_document(input_images_path=args.input_image_path, input_xml_path=args.input_xml_path, input_alto_path=args.input_alto_path)

    document = document_parser.process_document(document)

    if args.output_xml_path:
        document.to_pagexml(args.output_xml_path)

    if args.output_alto_path:
        document.to_altoxml(args.output_alto_path)

    print("Processing completed successfully.")

    return 0


if __name__ == "__main__":
    exit(main())
