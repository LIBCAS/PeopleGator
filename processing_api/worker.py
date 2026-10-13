import os
import sys
import logging
import argparse
import subprocess

from typing import Optional
from logging.handlers import TimedRotatingFileHandler

from doc_api.api.schemas.base_objects import Job
from doc_api.connector import Connector
from doc_worker.doc_worker_wrapper import DocWorkerWrapper, WorkerResponse


logger = logging.getLogger(__name__)


def parse_arguments():
    logger.info(' '.join(sys.argv))

    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", type=str, help="URL of the API endpoint.")
    parser.add_argument("--api-key", type=str, help="API key for authentication.")

    parser.add_argument("--base-dir", help="Base directory for jobs and engines (creates subdirectories 'jobs' and 'engines')", default="peoplegator_worker_data")
    parser.add_argument("--jobs-dir", help="Directory for job data (overrides base-dir/jobs)")
    parser.add_argument("--engines-dir", help="Directory for engine files (overrides base-dir/engines)")

    parser.add_argument("--polling-interval", default=1.0, type=float, help="Time in seconds to wait between job requests.")
    parser.add_argument("--cleanup-job-dir", action="store_true", help="Remove job directory after successful processing")
    parser.add_argument("--cleanup-old-engines", action="store_true", help="Remove old engine versions when downloading new ones")

    parser.add_argument("--logging-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="Logging level")
    parser.add_argument("--logging-format", type=str, default="[%(levelname)s|%(asctime)s|%(filename)s:%(name)s]: %(message)s", help="Logging format string")
    parser.add_argument("--logging-date-format", type=str, default="%Y-%m-%d_%H-%M-%S", help="Logging date format string")
    parser.add_argument("--log-file-path", type=str, default=None, required=False, help="Path to a directory where log files will be stored")

    parser.add_argument("--device", choices=["gpu", "cpu"], default="gpu")

    return parser.parse_args()


def setup_logging(logging_level, logging_format="", logging_date_format=None, log_file_path=None):
    level = logging.getLevelName(logging_level)

    console_log_formatter = logging.Formatter(logging_format, datefmt=logging_date_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        root_logger.addHandler(console_handler)

    if log_file_path is not None:
        time_rotating_file_handler = TimedRotatingFileHandler(
            filename=log_file_path,
            when="midnight",
            utc=True)

        root_logger.addHandler(time_rotating_file_handler)

    for root_handler in root_logger.handlers:
        root_handler.setFormatter(console_log_formatter)


class PeopleGatorWorker(DocWorkerWrapper):
    def __init__(self,
                 api_url: str,
                 connector: Connector,
                 base_dir: Optional[str] = None,
                 jobs_dir: Optional[str] = None,
                 engines_dir: Optional[str] = None,
                 polling_interval: float = 5.0,
                 cleanup_job_dir: bool = False,
                 cleanup_old_engines: bool = False,
                 download_engine_using_stream: bool = False,
                 device="cpu"):
        super().__init__(
            api_url=api_url,
            connector=connector,
            base_dir=base_dir,
            jobs_dir=jobs_dir,
            engines_dir=engines_dir,
            polling_interval=polling_interval,
            cleanup_job_dir=cleanup_job_dir,
            cleanup_old_engines=cleanup_old_engines,
            download_engine_using_stream=download_engine_using_stream
        )

        self.device = device

    def process_job(self,
                    job: Job,
                    job_log_file_handler: logging.FileHandler,
                    images_dir: str,
                    result_dir: str,
                    alto_dir: Optional[str] = None,
                    page_xml_dir: Optional[str] = None,
                    meta_file: Optional[str] = None,
                    engine_dir: Optional[str] = None) -> WorkerResponse:
        config_path = os.path.join(engine_dir, "config.ini")

        process_env = os.environ.copy()
        process_params = [
            "peoplegator",
            "--config", config_path,
            "--input-image-path", images_dir,
            "--output-alto-path", os.path.join(result_dir, "alto"),
            "--device", self.device
        ]

        if job.alto_required:
            process_params += ["--input-alto-path", alto_dir]

        if job.page_required:
            process_params += ["--input-xml-path", page_xml_dir]

        process = subprocess.Popen(
            process_params,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=process_env,
            text=True
        )

        stdout, stderr = process.communicate()
        result = WorkerResponse.ok()

        return result


def main():
    args = parse_arguments()

    if args.base_dir is not None:
        os.makedirs(args.base_dir, exist_ok=True)

    if args.jobs_dir is not None:
        os.makedirs(args.jobs_dir, exist_ok=True)

    if args.engines_dir is not None:
        os.makedirs(args.engines_dir, exist_ok=True)

    if args.log_file_path is not None:
        os.makedirs(os.path.dirname(args.log_file_path), exist_ok=True)

    setup_logging(args.logging_level,
                  logging_format=args.logging_format,
                  logging_date_format=args.logging_date_format,
                  log_file_path=args.log_file_path)

    connector = Connector(args.api_key, user_agent="PeopleGatorWorker/1.0")
    logger.debug("Connector initialized.")

    worker = PeopleGatorWorker(
        api_url=args.api_url,
        connector=connector,
        base_dir=args.base_dir,
        jobs_dir=args.jobs_dir,
        engines_dir=args.engines_dir,
        polling_interval=args.polling_interval,
        cleanup_job_dir=args.cleanup_job_dir,
        cleanup_old_engines=args.cleanup_old_engines,
        download_engine_using_stream=True,
        device=args.device
    )
    logger.debug("PeopleGatorWorker initialized.")

    logger.debug("Starting worker...")
    worker.start()
    logger.debug("Worker finished.")

    return 0


if __name__ == "__main__":
    exit(main())
