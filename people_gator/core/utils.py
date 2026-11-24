import os
import cv2
import json
import logging
import re

from anno_page.enums.language import Language
from people_gator.text.chunking import page_text, normalize_ocr, resolve_mappings, mapping_source_spans

from shapely.geometry import Polygon


logger = logging.getLogger(__name__)


def compose_path(file_path, reference_path):
    """Resolve a relative file path against a reference directory.

    Args:
        file_path: Absolute or relative file path.
        reference_path: Base directory for resolving relative paths.

    Returns:
        The original absolute path, or the path joined to the reference directory.
    """
    if reference_path and not os.path.isabs(file_path):
        file_path = os.path.join(reference_path, file_path)
    return file_path


def config_get_list(config, key, fallback=None, make_lowercase=False):
    """Read a JSON list setting, using the fallback for missing or invalid values.

    Args:
        config: INI configuration or engine section for this component.
        key: INI option containing a JSON list.
        fallback: Value returned for missing or invalid list settings.
        make_lowercase: Whether to lowercase string list items; defaults to False.

    Returns:
        The parsed list, optionally lowercased, or the supplied fallback.
    """
    if key not in config:
        return fallback

    try:
        value = json.loads(config[key])
    except json.decoder.JSONDecodeError as e:
        logger.warning("Invalid JSON list in configuration key %s; using fallback", key)
        return fallback

    if not isinstance(value, list):
        logger.warning("Configuration key %s is not a list; using fallback", key)
        return fallback

    if make_lowercase:
        value = [str(item).lower() if isinstance(item, str) else item for item in value]

    return value


def load_image(path):
    """Read a color image with OpenCV.

    Args:
        path: Image file path.

    Returns:
        A BGR color image array.

    Raises:
        Exception: If OpenCV cannot read the image.
    """
    image = cv2.imread(path, 1)
    if image is None:
        raise Exception(f'Unable to read image "{path}"')
    return image


def find_text_in_bounding_box(page_layout, bounding_box, min_overlap_ratio=0.5):
    """Return transcribed OCR lines meeting the overlap threshold, or None.

    Lines without a nonempty string transcription are skipped.

    Args:
        page_layout: Page layout supplying regions, OCR, or source references.
        bounding_box: Bounds as (x_min, y_min, x_max, y_max) in page pixels.
        min_overlap_ratio: Minimum fraction of line area inside the box; defaults to 0.5.
    """
    x_min, y_min, x_max, y_max = bounding_box
    bounding_box_polygon = Polygon([(x_min, y_min), (x_min, y_max), (x_max, y_max), (x_max, y_min)])

    lines = []
    for line in page_layout.lines_iterator():
        if not isinstance(line.transcription, str) or not line.transcription:
            continue
        line_polygon = Polygon(line.polygon)
        intersection_area = bounding_box_polygon.intersection(line_polygon).area
        line_area = line_polygon.area

        if line_area > 0 and intersection_area / line_area >= min_overlap_ratio:
            lines.append(line)

    text = None
    if len(lines) > 0:
        text = "\n".join([line.transcription for line in lines])

    return text


def find_source_region_by_bounding_box(page_layout, bounding_box, min_overlap_ratio=0.8):
    """Return the best-overlapping region meeting the threshold, or None.

    Args:
        page_layout: Page layout supplying regions, OCR, or source references.
        bounding_box: Bounds as (x_min, y_min, x_max, y_max) in page pixels.
        min_overlap_ratio: Minimum intersection/box-area ratio; defaults to 0.8.
    """
    x_min, y_min, x_max, y_max = bounding_box
    bounding_box_polygon = Polygon([(x_min, y_min), (x_min, y_max), (x_max, y_max)])
    bounding_box_area = bounding_box_polygon.area
    if bounding_box_area == 0:
        return None

    source_region = None
    source_region_overlap_ratio = 0.0

    for region in page_layout.regions:
        region_polygon = Polygon(region.polygon)
        intersection_area = bounding_box_polygon.intersection(region_polygon).area
        bounding_box_overlap_ratio = intersection_area / bounding_box_area

        if bounding_box_overlap_ratio >= min_overlap_ratio and bounding_box_overlap_ratio > source_region_overlap_ratio:
            source_region = region
            source_region_overlap_ratio = bounding_box_overlap_ratio

    return source_region


def assigned_caption(source_region):
    """Resolve the existing title caption, preferring Czech then English.

    Args:
        source_region: Image region with optional graphical metadata.
    """
    metadata = getattr(source_region, 'graphical_metadata', None)
    title = getattr(metadata, 'title', None)
    if isinstance(title, dict):
        title = title.get(Language.CZECH, title.get(Language.ENGLISH, next(iter(title.values()), None)))
    return title if isinstance(title, str) else None


def _comparison(text):
    """Make a whitespace/dehyphenation comparison copy, preserving stored evidence.

    Args:
        text: Source evidence or assigned caption text.
    """
    return normalize_ocr(text, casefold=False)[0].strip()



def caption_mentions(page, source_region, caption, occurrences):
    """Associate an assigned caption with original mentions and resolved sources.

    Usable caption-line references restrict the canonical OCR view; otherwise a
    unique page title or conservative complete-text evidence establishes a link.
    Repeated titles and identical text-only occurrences remain ambiguous.

    Args:
        page: Original page in OCR reading order.
        source_region: Image region with optional caption line references.
        caption: Assigned title string or None.
        occurrences: Ordered original mention/resolved span-line pairs.

    Returns:
        Associated mention/source pairs, without engine-specific prompt data.
    """
    metadata = getattr(source_region, 'graphical_metadata', None)
    caption_metadata = getattr(metadata, 'caption_lines_metadata', None)
    referenced_ids = {id(line) for line in (getattr(caption_metadata, 'lines', ()) or ())}
    caption_lines = [line for region in page.regions for line in region.lines
                     if id(line) in referenced_ids and isinstance(line.transcription, str)
                     and line.transcription.strip()]
    located, caption_spans = False, ()
    if caption and _comparison(caption):
        page_index = next((span.source.page_index for _, sources in occurrences for span, _ in sources), None)
        text, mappings, _ = page_text(page, page_index, lines=caption_lines or None)
        normalized, offsets = normalize_ocr(text, casefold=False)
        matches = [mapping_source_spans(resolve_mappings(mappings, offsets[m.start()][0], offsets[m.end() - 1][1]))
                   for m in re.finditer(r'(?<!\w)' + re.escape(_comparison(caption)) + r'(?!\w)', normalized)]
        located = bool(matches)
        caption_spans = matches[0] if len(matches) == 1 else ()
    captions = []
    for mention, sources in occurrences:
        if caption_lines or located:
            associated = bool(sources) and all(any(
                span.source.region_index == cap.source.region_index
                and span.source.line_index == cap.source.line_index
                and cap.start <= span.start < span.end <= cap.end
                for cap in caption_spans) for span, _ in sources)
        else:
            mapped = bool(mention.source_spans) or mention.line is not None
            evidence = _comparison(mention.text) if isinstance(mention.text, str) else ''
            associated = bool((not mapped or sources) and caption and evidence
                              and re.search(r'(?<!\w)' + re.escape(evidence) + r'(?!\w)', _comparison(caption)))
            if associated:
                associated = sum(_comparison(m.text) == evidence
                                 and _comparison(m.name) == _comparison(mention.name)
                                 for m, _ in occurrences) == 1
        if associated:
            captions.append((mention, sources))
    return captions
