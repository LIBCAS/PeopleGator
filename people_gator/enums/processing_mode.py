from enum import Enum


class ProcessingMode(Enum):
    SEQUENTIAL = 0
    PAGE_PARALLEL = 1
    DOCUMENT_PARALLEL = 2

    @staticmethod
    def from_string(mode_str: str):
        mode_str = mode_str.lower()
        if mode_str == "sequential":
            return ProcessingMode.SEQUENTIAL
        elif mode_str == "page_parallel":
            return ProcessingMode.PAGE_PARALLEL
        elif mode_str == "document_parallel":
            return ProcessingMode.DOCUMENT_PARALLEL
        else:
            raise ValueError(f"Unknown processing mode: {mode_str}")
