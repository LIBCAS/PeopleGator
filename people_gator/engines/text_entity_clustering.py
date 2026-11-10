"""Resolve document-wide mention candidates without changing OCR or identities."""

import json
import math
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from rapidfuzz.fuzz import partial_token_sort_ratio

from people_gator.core.layout import PeopleGatorDocument, PeopleGatorTextEntityCluster
from people_gator.engines.base import DocumentProcessingEngine
from people_gator.engines.llm import LLMBasedEngine, LLMResponseError


def _safe_text(value):
    """Reject blank text and non-whitespace control characters.

    Args:
        value: Proposed name or optional description string.
    """
    if not value.strip() or any(unicodedata.category(c) in {'Cc', 'Cs'} and c not in '\n\r\t' for c in value):
        raise ValueError('Expected nonblank text without control characters')
    return value


class TextEntityClusterResult(BaseModel):
    """One resolved group with a supplied name and request-local member indices."""

    name: str
    short_description: str | None
    long_description: str | None
    entity_indices: list[int]
    model_config = ConfigDict(extra='forbid', strict=True, revalidate_instances='always')

    @field_validator('name', 'short_description', 'long_description')
    @classmethod
    def validate_text(cls, value):
        """Validate output strings without rewriting their spelling.

        Args:
            value: Name or nullable description.
        """
        return _safe_text(value) if value is not None else None


class TextEntityClusteringResult(BaseModel):
    """Strict typed partition; membership is also checked against each request."""

    clusters: list[TextEntityClusterResult]
    model_config = ConfigDict(extra='forbid', strict=True, revalidate_instances='always')


def _normalized_name(value):
    """Normalize only comparison copies, retaining Unicode letters and numbers.

    Args:
        value: Name or OCR variant; original evidence is never changed.
    """
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', value).casefold()))


def _names(mention):
    """Return the canonical proposal and verbatim alias for a single record.

    Args:
        mention: Existing source mention, without a separate NER entity object.
    """
    canonical = mention.proposed_name if mention.proposed_name and mention.proposed_name.strip() else mention.name
    return canonical, mention.name


def _number(config, key, default):
    """Read a finite, nonnegative numeric option, rejecting booleans.

    Args:
        config: Engine INI section.
        key: Lowercase option name.
        default: Algorithmic default.
    """
    raw = config.get(key, str(default))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f'{key.upper()} must be finite and nonnegative') from None
    if isinstance(raw, bool) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{key.upper()} must be finite and nonnegative')
    return value


class LLMTextEntityClusteringEngine(DocumentProcessingEngine, LLMBasedEngine):
    """Stage a complete partition, protecting existing clusters and assignments."""

    def __init__(self, config, device, config_path):
        """Validate candidate options and initialize the shared external LLM config.

        Args:
            config: Engine ConfigParser section.
            device: Standard engine device; clustering requires no GPU.
            config_path: Base directory for externally supplied prompt resources.
        """
        self.threshold = _number(config, 'cluster_threshold', 92)
        if self.threshold > 100:
            raise ValueError('CLUSTER_THRESHOLD must be in 0–100')
        self.name_weight = _number(config, 'name_weight', .7)
        self.mention_weight = _number(config, 'mention_weight', .3)
        if self.name_weight + self.mention_weight <= 0 or not math.isfinite(self.name_weight + self.mention_weight):
            raise ValueError('NAME_WEIGHT and MENTION_WEIGHT must have a finite positive sum')
        self.aggregation = config.get('similarity_aggregation', 'max')
        if self.aggregation not in {'max', 'mean', 'min'}:
            raise ValueError('SIMILARITY_AGGREGATION must be max, mean or min')
        super().__init__(config, device, config_path)
        self.llm_prompter.raise_on_failure = True

    def similarity(self, first, second):
        """Compare canonical/alias pairs using the reference weighted fuzzy score.

        Args:
            first: First original mention.
            second: Second original mention.

        Returns:
            A candidate score from 0 to 100, never an identity decision.
        """
        total = self.name_weight + self.mention_weight
        weights = [self.name_weight / total, self.mention_weight / total]
        denominator = 2 * max(weights)
        scores = [partial_token_sort_ratio(_normalized_name(a), _normalized_name(b)) *
                  ((weights[i] + weights[j]) / denominator)
                  for i, a in enumerate(_names(first)) for j, b in enumerate(_names(second))]
        if self.aggregation == 'max':
            return max(scores)
        if self.aggregation == 'min':
            return min(scores)
        return sum(scores) / len(scores)

    def _candidate_groups(self, mentions):
        """Return threshold-graph components in input order (DBSCAN min_samples=1).

        Args:
            mentions: Unprotected mentions in document/page/mention order.
        """
        parents = list(range(len(mentions)))
        for i, first in enumerate(mentions):
            for j in range(i):
                if self.similarity(first, mentions[j]) >= self.threshold:
                    # Path compression keeps the graph representation linear in size.
                    a, b = i, j
                    while parents[a] != a:
                        a = parents[a]
                    while parents[b] != b:
                        b = parents[b]
                    parents[a] = b
        groups = {}
        for i, mention in enumerate(mentions):
            root = i
            while parents[root] != root:
                root = parents[root]
            parents[i] = root
            groups.setdefault(root, []).append(mention)
        return list(groups.values())

    @staticmethod
    def _singleton(mention):
        """Keep original metadata and any protected identity in a singleton.

        Args:
            mention: Original mention object; never mutated.
        """
        identity = mention.page_identity.identity if mention.page_identity else None
        return PeopleGatorTextEntityCluster([mention], identity, name=_names(mention)[0],
                                            description=mention.description)

    @staticmethod
    def _protected(document, mentions):
        """Validate and preserve existing groups; reject ambiguous prior membership.

        Args:
            document: Document with optional prior clusters.
            mentions: Unique source objects in deterministic input order.

        Raises:
            ValueError: Existing groups contain foreign/duplicate members or app-ID conflicts.
        """
        available = {id(m) for m in mentions}
        covered = set()
        for cluster in document.text_entity_clusters:
            members = [id(m) for m in cluster.text_entities]
            if not members or len(set(members)) != len(members) or any(m not in available or m in covered for m in members):
                raise ValueError('Existing text clusters have empty, foreign or duplicate membership')
            identities = [cluster.identity] + [m.page_identity.identity for m in cluster.text_entities if m.page_identity]
            app_ids = {i.peoplegator_id for i in identities if i is not None and i.peoplegator_id is not None}
            if len(app_ids) > 1:
                raise ValueError('Existing text cluster has conflicting app identities')
            covered.update(members)
        return list(document.text_entity_clusters), covered

    def _resolve(self, mentions):
        """Validate one LLM partition or conservatively keep every record separate.

        Args:
            mentions: Candidate component, numbered from one for this request only.

        Raises:
            RuntimeError: Transport or exhausted request; caller commits no clusters.
        """
        records = [{'index': index, 'name': _names(m)[0], 'aliases': [m.name],
                    'description': m.description, 'context': m.text}
                   for index, m in enumerate(mentions, start=1)]
        try:
            result = self.llm_prompter({'entities': json.dumps(records, ensure_ascii=False)},
                                       response_model=TextEntityClusteringResult)
        except (ValidationError, LLMResponseError):
            # A prompter may surface typed-content validation directly.
            result = {}
        except Exception as exc:
            self.logger.error('Text clustering request failed (%s)', type(exc).__name__)
            raise RuntimeError('Text clustering failed; check LLM service and request limits') from None
        if result is None:
            self.logger.error('Text clustering request exhausted without a result')
            raise RuntimeError('Text clustering failed; check LLM service and request limits')
        try:
            result = TextEntityClusteringResult.model_validate(result)
            indices = [i for c in result.clusters for i in c.entity_indices]
            if sorted(indices) != list(range(1, len(mentions) + 1)):
                raise ValueError('Partition must cover each request record exactly once')
            clusters = []
            for resolved in result.clusters:
                if not resolved.entity_indices:
                    raise ValueError('Empty cluster')
                members = [mentions[i - 1] for i in sorted(resolved.entity_indices)]
                observed = {_normalized_name(n) for m in members for n in _names(m)}
                if not _normalized_name(resolved.name) or _normalized_name(resolved.name) not in observed:
                    raise ValueError('Unsupported cluster name')
                clusters.append(PeopleGatorTextEntityCluster(
                    members, name=resolved.name,
                    description=resolved.long_description or resolved.short_description,
                    short_description=resolved.short_description))
            return clusters
        except (ValidationError, ValueError):
            self.logger.warning('Rejected text clustering partition; retaining %d singletons', len(mentions))
            return [self._singleton(m) for m in mentions]

    def process_document(self, document: PeopleGatorDocument) -> PeopleGatorDocument:
        """Commit a complete partition only after every request succeeds.

        Args:
            document: Source document, returned unchanged except its cluster list.

        Raises:
            ValueError: Prior annotations cannot form a safe partition.
            RuntimeError: LLM request failure; all prior annotations remain intact.
        """
        mentions = [m for page in document.page_layouts for m in page.text_entities]
        if len({id(m) for m in mentions}) != len(mentions):
            raise ValueError('A text mention object occurs more than once in the document')
        staged, covered = self._protected(document, mentions)
        candidates = []
        for mention in mentions:
            if id(mention) in covered:
                continue
            if mention.page_identity is not None:
                staged.append(self._singleton(mention))
            else:
                candidates.append(mention)
        groups = self._candidate_groups(candidates)
        self.logger.info('Text clustering: %d records, %d protected clusters, %d candidate groups',
                         len(mentions), len(staged), len(groups))
        for group in groups:
            staged.extend(self._resolve(group) if len(group) > 1 else [self._singleton(group[0])])
        order = {id(m): i for i, m in enumerate(mentions)}
        staged.sort(key=lambda c: min(order[id(m)] for m in c.text_entities))
        document.text_entity_clusters = staged
        self.logger.info('Text clustering completed: %d clusters, %d records', len(staged), len(mentions))
        return document
