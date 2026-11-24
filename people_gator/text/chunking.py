"""Page-local, line-aware character chunks with exact OCR provenance.

Offsets count Python Unicode characters, not bytes or tokens. Runtime imports
use only the standard library; layouts are read through their public fields.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import asdict, dataclass
import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from people_gator.core.layout import PeopleGatorDocument


@dataclass(frozen=True)
class SourceLine:
    """Document-local OCR address; indices refer to original layout lists.

    IDs are retained verbatim, including None. Indices disambiguate missing or
    repeated IDs at every level. Keys are meaningful within one source document.
    """

    page_index: int
    page_id: str | None
    region_index: int
    region_id: str | None
    line_index: int
    line_id: str | None


@dataclass(frozen=True)
class SourceSpan:
    """Canonical occurrence key: source address and half-open OCR offsets."""

    source: SourceLine
    start: int
    end: int

    def to_dict(self):
        """Return the flat OCR address and half-open offsets used in evidence."""
        return dict(asdict(self.source), start=self.start, end=self.end)


@dataclass(frozen=True)
class ChunkMapping:
    """Half-open chunk interval mapped to OCR, or a synthetic separator.

    source=None explicitly marks inserted text; line_start/line_end are then
    None. Otherwise both line offsets address the original transcription.
    """

    start: int
    end: int
    source: SourceLine | None = None
    line_start: int | None = None
    line_end: int | None = None


@dataclass(frozen=True)
class TextChunk:
    """Exact chunk text, document-wide index, and ordered complete mappings.

    page_start/page_end address the page's canonical newline-joined text.
    """

    index: int
    text: str
    page_index: int
    page_start: int
    page_end: int
    mappings: tuple[ChunkMapping, ...]

    def resolve(self, start: int, end: int) -> tuple[ChunkMapping, ...]:
        """Resolve a substring, retaining clipped synthetic separator entries.

        Args:
            start: Inclusive chunk character offset.
            end: Exclusive chunk character offset; an empty interval is valid.

        Raises:
            ValueError: If offsets are not integers or lie outside the chunk.
        """
        if (type(start) is not int or type(end) is not int
                or not 0 <= start <= end <= len(self.text)):
            raise ValueError("Expected integer offsets 0 <= start <= end <= len(chunk.text)")
        return resolve_mappings(self.mappings, start, end)

    def source_spans(self, start: int, end: int) -> tuple[SourceSpan, ...]:
        """Return normalized OCR keys for a substring, excluding separators.

        Args:
            start: Inclusive chunk character offset.
            end: Exclusive chunk character offset.
        """
        return mapping_source_spans(self.resolve(start, end))


def resolve_mappings(mappings, start, end):
    """Clip mapped intervals while retaining synthetic separators and OCR offsets.

    Args:
        mappings: Ordered mappings for the canonical text.
        start: Validated inclusive text offset.
        end: Validated exclusive text offset.
    """
    result = []
    for item in mappings:
        left, right = max(start, item.start), min(end, item.end)
        if left >= right:
            continue
        line_start = None if item.source is None else item.line_start + left - item.start
        line_end = None if item.source is None else line_start + right - left
        result.append(ChunkMapping(left, right, item.source, line_start, line_end))
    return tuple(result)


def mapping_source_spans(mappings):
    """Convert resolved mappings to OCR spans, merging contiguous same-line pieces.

    Args:
        mappings: Clipped source mappings, possibly including synthetic separators.
    """
    spans = []
    for item in mappings:
        if item.source is None:
            continue
        span = SourceSpan(item.source, item.line_start, item.line_end)
        if spans and spans[-1].source == span.source and spans[-1].end == span.start:
            span = SourceSpan(span.source, spans.pop().start, span.end)
        spans.append(span)
    return tuple(spans)


@dataclass(frozen=True)
class TextChunkCollection:
    """Immutable, ordered chunks; indices are contiguous from zero."""

    chunks: tuple[TextChunk, ...]


class TextChunker(ABC):
    """Reusable internal component for future text detectors."""

    @abstractmethod
    def chunk_document(self, document: PeopleGatorDocument) -> TextChunkCollection:
        """Return mapped OCR chunks without mutating the document.

        Args:
            document: Document whose page_layouts supply ordered OCR.
        """


class LineAwareTextChunker(TextChunker):
    """Greedy page-local windows, preferring complete line ends when possible."""

    def __init__(self, max_chars: int = 4096, overlap_chars: int = 0):
        """Set hard character budgets, including generated newlines.

        Args:
            max_chars: Maximum chunk length; defaults to 4096.
            overlap_chars: Exact canonical-text overlap; defaults to zero.
        """
        if type(max_chars) is not int or max_chars <= 0:
            raise ValueError("MAX_CHARS must be a positive integer")
        if type(overlap_chars) is not int or not 0 <= overlap_chars < max_chars:
            raise ValueError("OVERLAP_CHARS must be an integer with 0 <= OVERLAP_CHARS < MAX_CHARS")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk_document(self, document: PeopleGatorDocument) -> TextChunkCollection:
        """Chunk pages in document order, reading OCR without accessing images.

        Args:
            document: Source document; OCR and annotations remain unchanged.
        """
        chunks = []
        for page_index, page in enumerate(document.page_layouts):
            text, mappings, line_ends = page_text(page, page_index)
            mapping_ends = [item.end for item in mappings]
            start, previous_end = 0, 0
            while start < len(text):
                hard_end = min(start + self.max_chars, len(text))
                end = hard_end
                if hard_end < len(text):
                    boundary = bisect_right(line_ends, hard_end) - 1
                    minimum_end = max(previous_end + 1, start + self.overlap_chars + 1)
                    if boundary >= 0 and line_ends[boundary] >= minimum_end:
                        end = line_ends[boundary]
                selected = []
                for position in range(bisect_right(mapping_ends, start), len(mappings)):
                    item = mappings[position]
                    if item.start >= end:
                        break
                    left, right = max(start, item.start), min(end, item.end)
                    line_start = None if item.source is None else left - item.start
                    line_end = None if item.source is None else right - item.start
                    selected.append(ChunkMapping(left - start, right - start,
                                                 item.source, line_start, line_end))
                chunks.append(TextChunk(len(chunks), text[start:end], page_index,
                                        start, end, tuple(selected)))
                if end == len(text):
                    break
                previous_end = end
                start = end - self.overlap_chars
        return TextChunkCollection(tuple(chunks))


def page_text(page, page_index, lines=None):
    """Build canonical text and mappings in stable OCR reading order.

    Args:
        page: Layout with regions and optional reading_order mapping.
        page_index: Position in the original document page list.
        lines: Optional original line references to retain in OCR reading order.
    """
    line_ids = None if lines is None else {id(line) for line in lines}
    regions = list(enumerate(page.regions))
    order = page.reading_order or {}
    # Support the upstream object-key convention and XML reader's ID keys.
    regions.sort(key=lambda pair: _region_rank(pair[1], order))
    parts, mappings, line_ends = [], [], []
    offset = 0
    for region_index, region in regions:
        if region.category not in {None, "text"}:
            continue
        for line_index, line in enumerate(region.lines):
            if line_ids is not None and id(line) not in line_ids:
                continue
            value = line.transcription
            if not isinstance(value, str) or not value:
                continue
            if parts:
                parts.append("\n")
                mappings.append(ChunkMapping(offset, offset + 1))
                offset += 1
            source = SourceLine(page_index, page.id, region_index,
                                region.id, line_index, line.id)
            parts.append(value)
            mappings.append(ChunkMapping(offset, offset + len(value), source, 0, len(value)))
            offset += len(value)
            line_ends.append(offset)
    return "".join(parts), mappings, line_ends


def _region_rank(region, order):
    """Read upstream object or XML identifier ranks without requiring hashing.

    Args:
        region: Original region object.
        order: Layout reading-order mapping.
    """
    try:
        if region in order:
            return order[region]
    except TypeError:
        pass
    return order.get(region.id, float("inf"))


def text_chunker_factory(config: Mapping) -> TextChunker:
    """Create LINES from an unprefixed mapping or ConfigParser section.

    Args:
        config: Case-insensitive METHOD, MAX_CHARS, OVERLAP_CHARS options.
            Missing options default to LINES, 4096 and 0 respectively.
            LINE_AWARE is an alias for LINES. The future NER engine extracts
            CHUNKING_* options and strips their prefix before calling here.
            Unknown or duplicate keys and malformed values raise ValueError.
    """
    if not isinstance(config, Mapping):
        raise ValueError("Chunker configuration must be a mapping or ConfigParser section")
    options = {}
    for key, value in config.items():
        if not isinstance(key, str) or key.upper() not in {"METHOD", "MAX_CHARS", "OVERLAP_CHARS"}:
            raise ValueError(f"Unknown chunker option {key!r}; expected METHOD, MAX_CHARS or OVERLAP_CHARS")
        key = key.upper()
        if key in options:
            raise ValueError(f"Duplicate chunker option {key}")
        options[key] = value
    method = options.get("METHOD", "LINES")
    if method not in ("LINES", "LINE_AWARE"):
        raise ValueError(f"Unsupported chunker METHOD {method!r}; expected LINES (alias LINE_AWARE)")
    budgets = []
    for key, default in (("MAX_CHARS", 4096), ("OVERLAP_CHARS", 0)):
        value = options.get(key, default)
        if isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value.strip()):
            value = int(value)
        if type(value) is not int:
            raise ValueError(f"{key} must be an integer")
        budgets.append(value)
    return LineAwareTextChunker(*budgets)


def normalize_ocr(text, *, casefold=False):
    """Normalize whitespace/case and line hyphenation with character addresses.

    Args:
        text: Original evidence or OCR text.
        casefold: Expand Unicode casefolds when True; captions keep case by default.
    """
    chars, offsets = [], []
    removed = set()
    for match in re.finditer(r'[-\u00ad]\s*\n\s*', text):
        removed.update(range(match.start(), match.end()))
    for index, char in enumerate(text):
        if index in removed:
            continue
        for value in (' ' if char.isspace() else (char.casefold() if casefold else char)):
            if value == ' ' and chars and chars[-1] == ' ':
                offsets[-1] = (offsets[-1][0], index + 1)
            else:
                chars.append(value)
                offsets.append((index, index + 1))
    return ''.join(chars), offsets


def is_valid_text(value):
    """Test nonblank text for controls, without rewriting valid source strings.

    Args:
        value: Optional source or response value.
    """
    return (isinstance(value, str) and bool(value.strip())
            and not any(unicodedata.category(c) in {'Cc', 'Cs'} and c not in '\n\r\t' for c in value))
