import os
import cv2
import json
import logging


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