"""Source-grounded text evidence shared by both face assignment engines."""

from dataclasses import asdict
import re
from types import SimpleNamespace

from anno_page.enums.language import Language
from shapely.geometry import Polygon, box

from people_gator.text import LineAwareTextChunker, SourceLine, SourceSpan


def assigned_caption(source_region):
    """Resolve the existing title caption, preferring Czech then English.

    Args:
        source_region: Image region with optional graphical metadata.
    """
    metadata = getattr(source_region, 'graphical_metadata', None)
    title = getattr(metadata, 'title', None)
    if isinstance(title, dict):
        title = title.get(Language.CZECH, title.get(Language.ENGLISH, next(iter(title.values()), None)))
    return title if isinstance(title, str) else None


def _comparison(text):
    """Make a whitespace/dehyphenation comparison copy, preserving stored evidence.

    Args:
        text: Source evidence or assigned caption text.
    """
    return _normalized(text)[0].strip()


def _normalized(text):
    """Normalize whitespace/dehyphenation while retaining original character offsets.

    Args:
        text: Original OCR or caption text; case and spelling remain unchanged.
    """
    removed = set()
    for match in re.finditer(r'[-\u00ad]\s*\n\s*', text):
        removed.update(range(match.start(), match.end()))
    chars, offsets = [], []
    for index, char in enumerate(text):
        if index in removed:
            continue
        value = ' ' if char.isspace() else char
        if value == ' ' and chars and chars[-1] == ' ':
            offsets[-1] = (offsets[-1][0], index + 1)
        else:
            chars.append(value)
            offsets.append((index, index + 1))
    return ''.join(chars), offsets


def _contains(text, evidence):
    """Match complete source evidence with Unicode word boundaries, without guessing.

    Args:
        text: Assigned caption text.
        evidence: Original mention context, never its canonical proposal.
    """
    evidence = _comparison(evidence)
    return bool(evidence and re.search(r'(?<!\w)' + re.escape(evidence) + r'(?!\w)', _comparison(text)))


class FaceEntityContext:
    """Read-only, deterministic mention and cluster evidence for image requests."""

    def __init__(self, document=None):
        """Index original cluster membership by object identity.

        Args:
            document: Original document, or None for page-only callers.
        """
        self.document = document
        self.clusters = {}
        for cluster in getattr(document, 'text_entity_clusters', ()):
            for mention in cluster.text_entities:
                self.clusters.setdefault(id(mention), cluster)

    def _sources(self, page, page_index, mention):
        """Resolve valid original indices or a legacy line object to source spans.

        Args:
            page: Original page layout.
            page_index: Original page position in the document.
            mention: Existing detected or legacy mention.
        """
        spans = mention.source_spans
        if not spans and mention.line is not None and mention.span is not None:
            for ri, region in enumerate(page.regions):
                for li, line in enumerate(region.lines):
                    if line is mention.line:
                        spans = (SourceSpan(SourceLine(page_index, page.id, ri, region.id, li, line.id), *mention.span),)
                        break
        resolved = []
        for span in spans:
            source = span.source
            if source.page_index != page_index or not (0 <= source.region_index < len(page.regions)):
                return []
            region = page.regions[source.region_index]
            if not 0 <= source.line_index < len(region.lines):
                return []
            line = region.lines[source.line_index]
            if not isinstance(line.transcription, str) or not 0 <= span.start < span.end <= len(line.transcription):
                return []
            resolved.append((span, line))
        return resolved

    def _caption_sources(self, page, caption, caption_lines=None):
        """Locate a unique assigned title in OCR, retaining exact character provenance.

        Args:
            page: Original page, with supported OCR reading order.
            caption: Assigned caption string or None.
            caption_lines: Optional usable original line objects limiting title matches.

        Returns:
            Whether the title occurs within the allowed OCR lines and its unique
            source spans; repeats return True with no spans, preventing guessing.
        """
        if not caption or not _comparison(caption):
            return False, ()
        # One page-sized view reuses the chunker's reading order and mappings.
        # No extraction, image access or annotation mutation takes place.
        budget = 1 + sum(len(line.transcription) + 1 for region in page.regions
                         for line in region.lines if isinstance(line.transcription, str))
        chunks = LineAwareTextChunker(max_chars=budget).chunk_document(
            SimpleNamespace(page_layouts=[page])).chunks
        if not chunks:
            return False, ()
        chunk = chunks[0]
        text, offsets = _normalized(chunk.text)
        line_ids = None if caption_lines is None else {id(line) for line in caption_lines}
        matches = []
        for match in re.finditer(r'(?<!\w)' + re.escape(_comparison(caption)) + r'(?!\w)', text):
            spans = chunk.source_spans(offsets[match.start()][0], offsets[match.end() - 1][1])
            if line_ids is not None and not all(
                id(page.regions[span.source.region_index].lines[span.source.line_index]) in line_ids
                for span in spans
            ):
                continue
            matches.append(spans)
        return bool(matches), matches[0] if len(matches) == 1 else ()

    def _record(self, page, page_index, mention, locality):
        """Serialize a source occurrence and optional provisional cluster metadata.

        Args:
            page: Original page layout.
            page_index: Original page position.
            mention: Existing mention object.
            locality: Caption, surrounding, page or document evidence label.
        """
        result = {
            'provenance': locality, 'page_index': page_index, 'page_id': page.id,
            'name': mention.name, 'context': mention.text,
            'proposed_name': mention.proposed_name, 'description': mention.description,
            'source_spans': [dict(asdict(span.source), start=span.start, end=span.end)
                             for span, _ in self._sources(page, page_index, mention)],
        }
        cluster = self.clusters.get(id(mention))
        if cluster is not None:
            result['cluster'] = {'name': cluster.name, 'short_description': cluster.short_description,
                                 'description': cluster.description, 'provisional': True}
        return result

    def select(self, page, source_region, context_bbox, caption_text):
        """Select caption-only evidence or distinct surrounding/page/off-page sections.

        Usable original caption lines restrict title matching, but never replace
        character-level correspondence. Missing or unusable references fall back
        to a unique page title match, then complete verbatim context matching if
        the title is absent from OCR. Ambiguous titles remain unresolved.
        Normalized names never establish caption association. Surrounding locality
        uses positive area intersection of a mention line with the context crop.

        Args:
            page: Original page containing the image.
            source_region: Image region supplying the assigned caption.
            context_bbox: Existing image context crop in page coordinates.
            caption_text: Resolved title string or None.

        Returns:
            Four JSON-compatible collections; fallback collections are empty in
            the caption branch, including document_entities.
        """
        pages = self.document.page_layouts if self.document is not None else [page]
        page_index = next(i for i, item in enumerate(pages) if item is page)
        # Keep source-list order and remove only repeated references, not homonyms.
        mentions = list({id(m): m for m in getattr(page, 'text_entities', ())}.values())
        metadata = getattr(source_region, 'graphical_metadata', None)
        caption_metadata = getattr(metadata, 'caption_lines_metadata', None)
        referenced_ids = {id(line) for line in (getattr(caption_metadata, 'lines', ()) or ())}
        caption_lines = [line for region in page.regions for line in region.lines
                         if id(line) in referenced_ids and isinstance(line.transcription, str)
                         and line.transcription.strip()]
        located, caption_spans = self._caption_sources(page, caption_text, caption_lines or None)
        captions = []
        for mention in mentions:
            sources = self._sources(page, page_index, mention)
            if caption_lines or located:
                associated = bool(sources) and all(any(
                    span.source.region_index == cap.source.region_index
                    and span.source.line_index == cap.source.line_index
                    and cap.start <= span.start < span.end <= cap.end
                    for cap in caption_spans) for span, _ in sources)
            else:
                mapped = bool(mention.source_spans) or mention.line is not None
                associated = bool((not mapped or sources) and caption_text
                                  and isinstance(mention.text, str)
                                  and _contains(caption_text, mention.text))
                if associated:
                    # Identical context/name at distinct positions cannot identify
                    # which occurrence belongs to this text-only caption.
                    associated = sum(_comparison(m.text) == _comparison(mention.text)
                                     and _comparison(m.name) == _comparison(mention.name)
                                     for m in mentions) == 1
            if associated:
                captions.append(self._record(page, page_index, mention, 'caption'))
        result = {'caption_entities': captions, 'surrounding_entities': [],
                  'page_entities': [], 'document_entities': []}
        if captions:
            return result
        crop = box(*context_bbox)
        for mention in mentions:
            result['page_entities'].append(self._record(page, page_index, mention, 'page'))
            if any(Polygon(line.polygon).intersection(crop).area > 0
                   for _, line in self._sources(page, page_index, mention)):
                result['surrounding_entities'].append(self._record(page, page_index, mention, 'surrounding'))
        on_page = {id(self.clusters[id(m)]) for m in mentions if id(m) in self.clusters}
        seen_mentions, seen_clusters = set(), set()
        for pi, other_page in enumerate(pages):
            if other_page is page:
                continue
            for mention in getattr(other_page, 'text_entities', ()):
                if id(mention) in seen_mentions:
                    continue
                seen_mentions.add(id(mention))
                cluster = self.clusters.get(id(mention))
                if cluster is None:
                    result['document_entities'].append(self._record(other_page, pi, mention, 'document'))
                elif id(cluster) not in on_page and id(cluster) not in seen_clusters:
                    seen_clusters.add(id(cluster))
                    occurrences = []
                    seen_members = set()
                    for oi, off_page in enumerate(pages):
                        if off_page is page:
                            continue
                        for member in getattr(off_page, 'text_entities', ()):
                            if self.clusters.get(id(member)) is cluster and id(member) not in seen_members:
                                seen_members.add(id(member))
                                record = self._record(off_page, oi, member, 'document')
                                record.pop('cluster', None)
                                occurrences.append(record)
                    result['document_entities'].append({
                        'provenance': 'document', 'provisional': True,
                        'name': cluster.name, 'description': cluster.description,
                        'short_description': cluster.short_description,
                        'aliases': list(dict.fromkeys(m['name'] for m in occurrences)),
                        'sources': occurrences,
                    })
        return result
