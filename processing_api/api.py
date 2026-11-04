import os
import logging
from doc_api.run import main as doc_api_main


logger = logging.getLogger(__name__)


def main():
    """Start DocAPI with PeopleGator defaults, preserving environment overrides.

    Returns:
        Zero after the command completes normally.
    """
    config = {
        "SERVER_NAME": "PeopleGatorAPI",
        "APP_VERSION": "1.0.0",
        "APP_HOST": "0.0.0.0",
        "APP_PORT": "8000",
        "PRODUCTION": "False",
        "KEY_PREFIX": "peoplegator",
        "BASE_DIR": "./peoplegator_api_data",
    }

    for key, value in config.items():
        if not os.environ.get(key, None):
            os.environ[key] = value

    logger.info("Starting PeopleGator processing API")
    doc_api_main()
    return 0


if __name__ == "__main__":
    exit(main())
