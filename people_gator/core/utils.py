import os
import cv2
import json
import logging

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
