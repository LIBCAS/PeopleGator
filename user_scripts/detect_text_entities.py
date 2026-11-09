"""Inspect text detections from ALTO/PAGE without running other engine stages."""

import argparse
import configparser
import json
import logging
import os
from pathlib import Path
import sys
import tempfile


logger = logging.getLogger(__name__)


class InputError(ValueError):
    """An actionable CLI validation error safe to log without private payloads."""


def parse_arguments(argv=None):
    """Parse the detector-only command arguments.

    Args:
        argv: Optional argument list; None uses the process arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='Existing engine INI configuration.')
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--input-alto-path', help='Directory containing ALTO XML pages.')
    inputs.add_argument('--input-xml-path', help='Directory containing PAGE XML pages.')
    parser.add_argument('--output-path', help='Write UTF-8 JSON instead of a readable stdout summary.')
    parser.add_argument('--logging-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        default='INFO', help='Diagnostic logging level (default: INFO).')
    return parser.parse_args(argv)


def setup_logging(logging_level):
    """Configure stderr diagnostics, preserving existing handlers on repeated calls.

    Args:
        logging_level: DEBUG, INFO, WARNING or ERROR selected by the CLI.
    """
    level = logging.getLevelName(logging_level)
    logging.basicConfig(level=level,
                        format='[%(levelname)s|%(asctime)s|%(name)s]: %(message)s',
                        datefmt='%Y-%m-%d_%H-%M-%S')
    logging.getLogger().setLevel(level)


def load_detector(config_path):
    """Select exactly one text detector without constructing other engines/services.

    Args:
        config_path: Path to the existing INI file; relative resources use its parent.
    """
    from people_gator.core.document_parser import engine_factory

    config_path = Path(config_path).resolve()
    config = configparser.ConfigParser()
    with config_path.open(encoding='utf-8') as stream:
        config.read_file(stream)
    sections = [section for section in config.sections()
                if section.startswith('ENGINE_') and
                config[section].get('METHOD') == 'TEXT_ENTITY_DETECTION']
    if len(sections) != 1:
        raise InputError('Configuration must contain exactly one [ENGINE_*] section '
                         f'with METHOD = TEXT_ENTITY_DETECTION; found {len(sections)}.')
    return engine_factory(config[sections[0]], config_path=str(config_path.parent), device='cpu')


def load_document(directory, alto):
    """Validate XML files, then reuse the standard image-free document loader/order.

    Args:
        directory: Input directory containing page XML files.
        alto: True selects ALTO; False selects PAGE XML.
    """
    from lxml import etree
    from people_gator.core.layout import PeopleGatorDocument

    directory = Path(directory)
    if not directory.is_dir():
        raise InputError('Input XML path must be an existing directory.')
    files = [path for path in directory.iterdir() if path.name.lower().endswith('.xml')]
    if not files:
        raise InputError('Input directory contains no XML files.')
    expected = 'alto' if alto else 'PcGts'
    for path in files:
        try:
            root = etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True)).getroot()
            if etree.QName(root).localname != expected or not root.xpath(".//*[local-name()='Page']"):
                raise InputError(f'Input XML must contain a {expected} root and a Page element.')
        except InputError:
            raise
        except Exception as exc:
            raise InputError(f'Cannot read input XML file {path.name!r} ({type(exc).__name__}).') from None
    return PeopleGatorDocument(**{'alto_xmls_dir' if alto else 'page_xmls_dir': str(directory)})


def detection_result(document):
    """Return a JSON-safe snapshot in document/page/mention/source-span order.

    Args:
        document: Detector-updated document; no layout objects are serialized.
    """
    mentions = []
    for page in document.page_layouts:
        for mention in page.text_entities:
            spans = []
            for span in mention.source_spans:
                source = span.source
                spans.append({
                    'page_id': source.page_id, 'region_id': source.region_id, 'line_id': source.line_id,
                    'page_index': source.page_index, 'region_index': source.region_index,
                    'line_index': source.line_index, 'start': span.start, 'end': span.end,
                })
            mentions.append({'name': mention.name, 'proposed_name': mention.proposed_name,
                             'description': mention.description, 'context': mention.text,
                             'source_spans': spans})
    return {'document_id': document.id, 'mentions': mentions}


def readable_result(result):
    """Format a compact listing, preserving readable Unicode and multiline names.

    Args:
        result: JSON-safe detection snapshot.
    """
    if not result['mentions']:
        return 'No text entity mentions detected.\n'
    lines = [f"Detected {len(result['mentions'])} text entity mention(s):"]
    for mention in result['mentions']:
        name = json.dumps(mention['name'], ensure_ascii=False)
        locations = [f"page {s['page_id']!r} [{s['page_index']}], "
                     f"region {s['region_id']!r} [{s['region_index']}], "
                     f"line {s['line_id']!r} [{s['line_index']}] "
                     f"chars [{s['start']}, {s['end']})" for s in mention['source_spans']]
        lines.append(f"- {name}: " + '; '.join(locations))
    return '\n'.join(lines) + '\n'


def write_json(output_path, result):
    """Replace output only after a complete UTF-8 JSON file has been written.

    Args:
        output_path: Target file; missing parent directories are created.
        result: Complete JSON-safe detection snapshot.
    """
    payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output_path.parent,
                                         prefix='.entities-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    """Detect text entities and return a nonzero status on any processing failure.

    Args:
        argv: Optional argument list; None uses the process arguments.
    """
    args = parse_arguments(argv)
    setup_logging(args.logging_level)
    stage = 'Configuration'
    try:
        logger.debug('Initializing configured text detector')
        detector = load_detector(args.config)
        stage = 'XML loading'
        document = load_document(args.input_alto_path or args.input_xml_path,
                                 alto=args.input_alto_path is not None)
        logger.info('Loaded %d pages for text detection', len(document.page_layouts))
        stage = 'Text detection'
        document = detector.process_document(document)
        result = detection_result(document)
        stage = 'Output writing'
        if args.output_path:
            write_json(args.output_path, result)
        else:
            sys.stdout.write(readable_result(result))
    except InputError as exc:
        logger.error('Error: %s', exc)
        return 1
    except Exception as exc:
        # Exception messages from providers/XML/config parsing can expose private data.
        logger.error('Error: %s failed (%s); check the configuration, input files, '
                     'service, or output permissions.', stage, type(exc).__name__)
        return 1
    logger.info('Text detection CLI completed: %d mentions', len(result['mentions']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
