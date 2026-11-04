from enum import Enum


class ProcessingMode(Enum):
    """Sequential, page-parallel, or document-parallel LLM scheduling."""
    SEQUENTIAL = 0
    PAGE_PARALLEL = 1
    DOCUMENT_PARALLEL = 2

    @staticmethod
    def from_string(mode_str: str):
        """Return the case-insensitive processing mode for a supported name.

        Args:
            mode_str: One of sequential, page_parallel, or document_parallel (case-insensitive).

        Raises:
            ValueError: If the processing mode is unsupported.
        """
        mode_str = mode_str.lower()
        if mode_str == "sequential":
            return ProcessingMode.SEQUENTIAL
        elif mode_str == "page_parallel":
            return ProcessingMode.PAGE_PARALLEL
        elif mode_str == "document_parallel":
            return ProcessingMode.DOCUMENT_PARALLEL
        else:
            raise ValueError(f"Unknown processing mode: {mode_str}")
