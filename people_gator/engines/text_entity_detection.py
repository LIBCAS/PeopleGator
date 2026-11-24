"""Extract person-like beings while retaining exact OCR occurrence addresses."""

import logging
import re
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, ConfigDict, PrivateAttr, ValidationError, field_validator, model_validator

from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine
from people_gator.core.layout import PeopleGatorDocument, PeopleGatorTextEntityMention
from people_gator.text import text_chunker_factory
from people_gator.text.chunking import normalize_ocr

logger = logging.getLogger(__name__)


class TextEntityMentionResult(BaseModel):
    """Verbatim name and contiguous context proposed for one OCR occurrence."""

    name: str
    context: str
    model_config = ConfigDict(extra='forbid', strict=True)

    @field_validator('name', 'context')
    @classmethod
    def require_evidence(cls, value):
        """Reject empty evidence without stripping or rewriting source characters.

        Args:
            value: Validated string from the LLM result.
        """
        if not value.strip():
            raise ValueError('Evidence must contain non-whitespace characters')
        return value


class TextEntityResult(BaseModel):
    """A person-like entity proposal with individually validated mention evidence."""

    name: str
    type: Literal['being']
    info: str | None
    mentions: list[TextEntityMentionResult]
    model_config = ConfigDict(extra='forbid', strict=True)
    _rejected_mentions: int = PrivateAttr(default=0)

    @field_validator('name')
    @classmethod
    def require_name(cls, value):
        """Reject an empty canonical proposal while retaining its original spelling.

        Args:
            value: Validated proposed entity name.
        """
        if not value.strip():
            raise ValueError('Entity name must contain non-whitespace characters')
        return value

    @model_validator(mode='wrap')
    @classmethod
    def validate_mentions(cls, value, handler):
        """Validate entity metadata, skipping malformed mentions independently.

        Args:
            value: Raw candidate mapping or already validated entity.
            handler: Pydantic validation continuation.
        """
        if not isinstance(value, dict) or not isinstance(value.get('mentions'), list):
            return handler(value)
        result = handler({**value, 'info': value.get('info'), 'mentions': []})
        for mention in value['mentions']:
            try:
                result.mentions.append(TextEntityMentionResult.model_validate(mention))
            except ValidationError:
                result._rejected_mentions += 1
        return result


class TextEntityDetectionResult(BaseModel):
    """Typed extraction response retaining valid candidates and safe rejection counts."""

    entities: list[TextEntityResult]
    model_config = ConfigDict(extra='forbid', strict=True)
    _rejected_candidates: int = PrivateAttr(default=0)

    @model_validator(mode='wrap')
    @classmethod
    def validate_entities(cls, value, handler):
        """Normalize legacy arrays and skip only malformed entity candidates.

        Args:
            value: Raw JSON response or already validated extraction result.
            handler: Pydantic validation continuation.
        """
        if isinstance(value, list):
            value = {'entities': value}
        if not isinstance(value, dict) or not isinstance(value.get('entities'), list):
            return handler(value)
        result = handler({**value, 'entities': []})
        for entity in value['entities']:
            try:
                candidate = TextEntityResult.model_validate(entity)
            except ValidationError:
                result._rejected_candidates += 1
                continue
            result.entities.append(candidate)
            result._rejected_candidates += candidate._rejected_mentions
        return result


def _occurrences(text, needle):
    """Return all overlapping exact intervals.

    Args:
        text: Searchable source.
        needle: Nonempty evidence string.
    """
    return [(m.start(), m.start() + len(needle))
            for m in re.finditer('(?=' + re.escape(needle) + ')', text)] if needle else []



def _locate(text, evidence, cutoff):
    """Find exact, normalized, then bounded fuzzy evidence, rejecting ties.

    Args:
        text: Source search window.
        evidence: Requested extractive evidence.
        cutoff: Minimum fuzzy similarity percentage.
    """
    exact = _occurrences(text, evidence)
    if exact:
        return exact
    normalized, offsets = normalize_ocr(text, casefold=True)
    wanted, _ = normalize_ocr(evidence, casefold=True)
    if not wanted.strip():
        return []
    matches = _occurrences(normalized, wanted)
    if matches:
        return list(dict.fromkeys((offsets[a][0], offsets[b - 1][1]) for a, b in matches))
    # Fuzzy matching is deliberately limited to word-boundary windows and
    # evidence of >=5 characters. At most 512 starts and 32 ends per start.
    if len(wanted) < 5 or len(wanted) > 512:
        return []
    starts = [m.start() for m in re.finditer(r'\w+', normalized)]
    ends = [m.end() for m in re.finditer(r'\w+', normalized)]
    if len(starts) > 512:
        return []
    scored = []
    for start in starts:
        candidates = [end for end in ends if end > start and
                      .8 * len(wanted) <= end - start <= 1.2 * len(wanted)]
        for end in candidates[:32]:
            score = 100 * SequenceMatcher(None, wanted, normalized[start:end], autojunk=False).ratio()
            if score >= cutoff:
                scored.append((score, offsets[start][0], offsets[end - 1][1]))
    if not scored:
        return []
    best = max(score for score, _, _ in scored)
    winners = {(a, b) for score, a, b in scored if score >= best - 2}
    return list(winners) if len(winners) == 1 else []


def match_mention(text, name, context, cutoff=80):
    """Resolve a unique name occurrence inside uniquely supported context.

    Args:
        text: Chunk OCR text.
        name: Mention evidence (not canonical name).
        context: Supporting contiguous evidence.
        cutoff: Minimum fuzzy score; defaults to 80.

    Returns:
        Name and context intervals, or None for absent/ambiguous evidence.
    """
    contexts = _locate(text, context, cutoff)
    candidates = []
    for a, b in contexts:
        for start, end in _locate(text[a:b], name, cutoff):
            candidates.append((a + start, a + end, a, b))
    candidates = list(dict.fromkeys(candidates))
    return candidates[0] if len(candidates) == 1 else None


class LLMTextEntityDetectionEngine(DocumentProcessingEngine, LLMBasedEngine):
    """Stage unresolved OCR mentions atomically; never assign app identities."""

    def __init__(self, config, device, config_path):
        """Configure the shared LLM service and an independent chunker.

        Args:
            config: Engine ConfigParser section.
            device: Existing engine device setting; inference is remote.
            config_path: Base directory for configured LLM resource paths.
        """
        super().__init__(config, device, config_path)
        self.chunker = text_chunker_factory({key.upper().removeprefix('CHUNKING_'): value
                                            for key, value in self.config.items()
                                            if key.upper().startswith('CHUNKING_')})
        self.match_cutoff = self.config.getfloat('mention_match_score_cutoff', 80.0)
        if not 0 <= self.match_cutoff <= 100:
            raise ValueError('MENTION_MATCH_SCORE_CUTOFF must be numeric in 0–100')

    def process_document(self, document: PeopleGatorDocument) -> PeopleGatorDocument:
        """Process all chunks before appending any new mentions.

        Args:
            document: Source document; OCR/layout objects are retained.

        Raises:
            RuntimeError: Request failure or invalid top-level extraction response.
        """
        staged = {}
        existing_spans = {id(page): {m.source_spans for m in page.text_entities if m.source_spans}
                          for page in document.page_layouts}
        legacy_spans = {id(page): {} for page in document.page_layouts}
        for page in document.page_layouts:
            for mention in page.text_entities:
                if mention.line is not None and mention.span is not None:
                    legacy_spans[id(page)].setdefault(id(mention.line), []).append(mention.span)
        for chunk in self.chunker.chunk_document(document).chunks:
            if not chunk.text.strip():
                continue
            try:
                result = self.llm_prompter({'text': chunk.text},
                                           response_model=TextEntityDetectionResult)
                result = TextEntityDetectionResult.model_validate(result)
            except Exception as exc:
                logger.error('Text detection page=%d chunk=%d failed (%s)',
                             chunk.page_index, chunk.index, type(exc).__name__)
                raise RuntimeError(f'Text detection failed at page {chunk.page_index}, chunk {chunk.index}; '
                                   'check LLM service and response format') from None
            rejected = result._rejected_candidates
            for entity in result.entities:
                for mention in entity.mentions:
                    match = match_mention(chunk.text, mention.name, mention.context, self.match_cutoff)
                    if match is None:
                        rejected += 1
                        continue
                    start, end, a, b = match
                    spans = chunk.source_spans(start, end)
                    if not spans:
                        rejected += 1
                        continue
                    page = document.page_layouts[chunk.page_index]
                    if spans in staged or spans in existing_spans[id(page)]:
                        continue
                    line = page.regions[spans[0].source.region_index].lines[spans[0].source.line_index] if len(spans) == 1 else None
                    span = (spans[0].start, spans[0].end) if line is not None else None
                    if line is not None and span in legacy_spans[id(page)].get(id(line), ()):
                        continue
                    staged[spans] = (page, PeopleGatorTextEntityMention(
                        name=chunk.text[start:end], text=chunk.text[a:b], line=line, span=span,
                        source_spans=spans, proposed_name=entity.name, description=entity.info))
            logger.debug('Text detection page=%d chunk=%d entities=%d rejected=%d',
                         chunk.page_index, chunk.index, len(result.entities), rejected)
        for page, mention in staged.values():
            page.text_entities.append(mention)
        logger.info('Text detection added %d mentions', len(staged))
        return document
