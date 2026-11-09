"""Reusable OCR text chunking, independent of document-processing engines."""

from .chunking import (
    ChunkMapping,
    LineAwareTextChunker,
    SourceLine,
    SourceSpan,
    TextChunk,
    TextChunkCollection,
    TextChunker,
    text_chunker_factory,
)

__all__ = [
    "ChunkMapping", "LineAwareTextChunker", "SourceLine", "SourceSpan",
    "TextChunk", "TextChunkCollection", "TextChunker", "text_chunker_factory",
]
