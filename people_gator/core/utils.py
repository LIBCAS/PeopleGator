import os
import cv2
import json
import logging

from shapely.geometry import Polygon


logger = logging.getLogger(__name__)


def compose_path(file_path, reference_path):
    if reference_path and not os.path.isabs(file_path):
        file_path = os.path.join(reference_path, file_path)
    return file_path


def config_get_list(config, key, fallback=None, make_lowercase=False):
    if key not in config:
        return fallback

    try:
        value = json.loads(config[key])
    except json.decoder.JSONDecodeError as e:
        logger.info(f'Failed to parse list from config key "{key}", returning fallback {fallback}:\n{e}')
        return fallback

    if not isinstance(value, list):
        logger.info(f'Config key "{key}" is not a list (got {type(value).__name__}), returning fallback {fallback}.')
        return fallback

    if make_lowercase:
        value = [str(item).lower() if isinstance(item, str) else item for item in value]

    return value


def load_image(path):
    image = cv2.imread(path, 1)
    if image is None:
        raise Exception(f'Unable to read image "{path}"')
    return image


def find_text_in_bounding_box(page_layout, bounding_box, min_overlap_ratio=0.5):
    x_min, y_min, x_max, y_max = bounding_box
    bounding_box_polygon = Polygon([(x_min, y_min), (x_min, y_max), (x_max, y_max), (x_max, y_min)])

    lines = []
    for line in page_layout.lines_iterator():
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
