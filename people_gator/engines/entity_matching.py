"""Conservative document-wide resolution of clustered text and named faces."""

from dataclasses import dataclass, field
import logging
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from people_gator.engines import DocumentProcessingEngine, LLMBasedEngine
from people_gator.engines.face_entity_context import FaceEntityContext, assigned_caption
from people_gator.core.layout import PeopleGatorDocument, PeopleGatorIdentity, PeopleGatorFaceRegionLayout


logger = logging.getLogger(__name__)


def _text(value):
    """Return usable source text without exposing it in diagnostics.

    Args:
        value: Optional name, description or context.
    """
    if not isinstance(value, str) or any(unicodedata.category(c) in {'Cc', 'Cs'}
                                         and c not in '\n\r\t' for c in value):
        return ''
    return value.strip()


def _strings(values):
    """Deduplicate nonblank strings in source order using comparison copies.

    Args:
        values: Source strings; stored annotations are never rewritten.
    """
    result, seen = [], set()
    for value in values:
        value = _text(value)
        key = ' '.join(value.casefold().split())
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _name_keys(names):
    """Return exact normalized names for retrieval and caption reconciliation.

    Args:
        names: Proposed names and observed aliases.
    """
    return {' '.join(unicodedata.normalize('NFKC', n).casefold().split()) for n in _strings(names)}


def _name_only(quote, names):
    """Reject punctuation-only evidence and fragments composed only of name tokens.

    Args:
        quote: Claimed contextual evidence, already checked against original text.
        names: Supplied canonical name and aliases for that side of the comparison.
    """
    tokens = set(re.findall(r'\w+', unicodedata.normalize('NFKC', quote).casefold()))
    name_tokens = {token for name in _strings(names)
                   for token in re.findall(r'\w+', unicodedata.normalize('NFKC', name).casefold())}
    return not tokens or tokens <= name_tokens


class EntityMatchingEvidence(BaseModel):
    """Verbatim contextual evidence comparing the source with one candidate."""

    item_id: int
    source_quote: str
    candidate_quote: str
    model_config = ConfigDict(extra='forbid', strict=True, revalidate_instances='always')


class EntityMatchingResult(BaseModel):
    """An explicit selection, justified creation or unresolved person decision."""

    action: Literal['select', 'create', 'unresolved']
    source_is_person: bool
    item_id: int | None
    name: str | None
    reason: str
    evidence: list[EntityMatchingEvidence]
    model_config = ConfigDict(extra='forbid', strict=True, revalidate_instances='always')

    @field_validator('reason')
    @classmethod
    def validate_reason(cls, value):
        """Require an explanation without logging private decision text.

        Args:
            value: Model explanation based only on supplied evidence.
        """
        if not _text(value):
            raise ValueError('A nonblank reason is required')
        return value

    @model_validator(mode='after')
    def validate_action(self):
        """Reject contradictory action fields, even without provider enforcement."""
        if self.action == 'unresolved':
            if self.item_id is not None or self.name is not None or self.evidence:
                raise ValueError('Unresolved decisions must not specify a candidate or evidence')
        elif not self.source_is_person or not _text(self.name):
            raise ValueError('Linking requires a named person source')
        elif self.action == 'select' and (self.item_id is None or self.item_id < 0):
            raise ValueError('Selection requires a nonnegative candidate index')
        elif self.action == 'create' and self.item_id is not None:
            raise ValueError('Creation cannot select an existing candidate')
        return self


@dataclass(eq=False)
class _LinkUnit:
    """Original references that have explicit or unique caption identity evidence."""

    order: int = 0
    clusters: list = field(default_factory=list)
    faces: list = field(default_factory=list)

    def identities(self):
        """Return distinct existing person objects, retaining their metadata."""
        values = [c.identity for c in self.clusters]
        values.extend(getattr(m.page_identity, 'identity', None)
                      for c in self.clusters for m in c.text_entities)
        values.extend(f.face_metadata.page_identity.identity for _, f in self.faces)
        return list({id(i): i for i in values if i is not None}.values())

    def targets(self):
        """Return original objects used to recognize uncertain writes on retries."""
        return [*self.clusters, *(i for i in self.identities())]

    def evidence(self, context):
        """Collect source names, facts, captions and original mention provenance.

        Args:
            context: Shared read-only source-mapping selector.
        """
        names = [c.name for c in self.clusters]
        names.extend(i.name for i in self.identities())
        names.extend(n for c in self.clusters for m in c.text_entities for n in (m.proposed_name, m.name))
        names = _strings(names)
        descriptions = _strings([d for c in self.clusters for d in (c.short_description, c.description)] +
                                [m.description for c in self.clusters for m in c.text_entities])
        sources = []
        for c in self.clusters:
            for m in c.text_entities:
                page = next((p for p in context.document.page_layouts
                             if any(member is m for member in getattr(p, 'text_entities', ()))), None)
                if page is not None:
                    sources.append(context._record(page, context._page_index(page), m, 'text'))
        captions = _strings([assigned_caption(f.source_region) for _, f in self.faces])
        return {'name': names[0] if names else '', 'aliases': names[1:],
                'short_description': next((_text(c.short_description) for c in self.clusters
                                           if _text(c.short_description)), ''),
                'description': next((_text(c.description) for c in self.clusters if _text(c.description)),
                                    '\n'.join(_strings(m.description for c in self.clusters for m in c.text_entities))),
                'descriptions': descriptions, 'sources': sources, 'captions': captions}


class EntityMatchingEngine(DocumentProcessingEngine, LLMBasedEngine):
    """Resolve document identities without treating retrieval as identity proof."""

    def __init__(self, config, device, config_path, db_api_service=None):
        """Initialize the existing engine key, external prompt and shared app client.

        Args:
            config: Engine INI section.
            device: Standard processing device; linking requires no GPU.
            config_path: Base directory for external JSON/Jinja prompt resources.
            db_api_service: Optional authenticated PeopleGatorApp client.
        """
        super().__init__(config, device, config_path)
        self.db_api_service = db_api_service
        self.llm_prompter.raise_on_failure = True

    def _units(self, document, context):
        """Gather clusters once, group shared objects and reconcile unique captions.

        Args:
            document: Original document whose clustering must remain unchanged.
            context: Source-mapped caption selector for this document.
        """
        clusters = list(dict.fromkeys(document.text_entity_clusters))
        available = {id(m) for page in document.page_layouts for m in getattr(page, 'text_entities', ())}
        assigned = set()
        for cluster in clusters:
            members = [id(m) for m in cluster.text_entities]
            if (not members or len(set(members)) != len(members)
                    or assigned.intersection(members) or set(members) - available):
                raise ValueError('Entity matching requires nonempty, disjoint original cluster members')
            assigned.update(members)
        units = [_LinkUnit(order=i, clusters=[c]) for i, c in enumerate(clusters)]
        for page in document.page_layouts:
            for face in (r for r in page.regions if isinstance(r, PeopleGatorFaceRegionLayout)):
                metadata = face.face_metadata
                identity = getattr(getattr(metadata, 'page_identity', None), 'identity', None)
                if identity is not None and _text(identity.name):
                    units.append(_LinkUnit(order=len(units), faces=[(page, face)]))
        # Object identity, never name equality, establishes explicit shared links.
        owners = {}
        for unit in list(units):
            matches = list(dict.fromkeys(owners[id(i)] for i in unit.identities() if id(i) in owners))
            for other in matches:
                unit.order = min(unit.order, other.order)
                unit.clusters = other.clusters + unit.clusters
                unit.faces = other.faces + unit.faces
                units.remove(other)
                for key, owner in list(owners.items()):
                    if owner is other:
                        owners[key] = unit
            for identity in unit.identities():
                owners[id(identity)] = unit
        # A named face may join one relevant caption cluster. Page co-occurrence
        # and non-caption/background entities never establish this relationship.
        membership = {id(m): u for u in units for c in u.clusters for m in c.text_entities}
        for unit in list(units) if membership else ():
            if unit.clusters or not unit.faces:
                continue
            supported = set()
            for page, face in unit.faces:
                caption = assigned_caption(face.source_region)
                records = context.select(page, face.source_region, (0, 0, 0, 0), caption)['caption_entities']
                name = face.face_metadata.page_identity.identity.name
                relevant = set()
                for mention in getattr(page, 'text_entities', ()):
                    target = membership.get(id(mention))
                    if target is None:
                        continue
                    record = context._record(page, context._page_index(page), mention, 'caption')
                    if record['source_spans'] and record in records:
                        names = target.evidence(context)
                        if _name_keys([name]) & _name_keys([names['name'], *names['aliases']]):
                            relevant.add(target)
                if len(relevant) == 1:
                    supported.update(relevant)
            if len(supported) == 1:
                target = next(iter(supported))
                ids = {i.peoplegator_id for u in (unit, target) for i in u.identities()
                       if i.peoplegator_id is not None}
                if len(ids) <= 1:
                    target.faces.extend(unit.faces)
                    units.remove(unit)
        # Preserve source order even when several explicit reference groups join.
        cluster_order = {id(c): i for i, c in enumerate(clusters)}
        face_order = {id(f): (pi, ri) for pi, p in enumerate(document.page_layouts)
                      for ri, f in enumerate(p.regions)}
        for unit in units:
            unit.clusters.sort(key=lambda c: cluster_order[id(c)])
            unit.faces.sort(key=lambda pair: face_order[id(pair[1])])
        return sorted(units, key=lambda u: u.order)

    def process_document(self, document: PeopleGatorDocument):
        """Resolve stable source units and propagate only successful app operations.

        Args:
            document: Original document, updated in place and returned unchanged in identity.

        Raises:
            RuntimeError: A read, model request or uncertain create failed. Earlier
                successful IDs remain applied; uncertain writes are blocked on retry.
        """
        if self.db_api_service is None:
            logger.warning('Database API service is not initialized. Skipping entity matching.')
            return document
        context = FaceEntityContext(document)
        units = self._units(document, context)
        cache = {}
        known = []
        for unit in units:
            source = unit.evidence(context)
            for identity in unit.identities():
                if identity.peoplegator_id is not None:
                    known.append((source, identity.peoplegator_id))
        logger.info('Entity matching: %d document identity units', len(units))
        for position, unit in enumerate(units):
            identities = unit.identities()
            protected = {i.peoplegator_id for i in identities if i.peoplegator_id is not None}
            if len(protected) > 1:
                logger.warning('Entity unit %d: conflicting protected IDs; unchanged', position)
                continue
            if protected and not all(_text(value) for value in protected):
                logger.warning('Entity unit %d: unusable protected ID; unchanged', position)
                continue
            if protected:
                self._apply(document, unit, next(iter(protected)))
                continue
            source = unit.evidence(context)
            name = source['name']
            if (not name or not any(c.isalpha() for c in name)
                    or name.casefold() in {'none', 'null', 'unknown', 'unnamed', 'unidentified', 'person'}):
                logger.debug('Entity unit %d: no usable person proposal', position)
                continue
            pending = document.entity_linking_journal
            targets = unit.targets()
            receipts = [r for r in pending if any(a is b for a in targets for b in r['targets'])]
            names = _name_keys([name, *source['aliases']])
            if any(record['state'] == 'uncertain' and (record in receipts or
                   names & _name_keys([record['source']['name'], *record['source']['aliases']]))
                   for record in pending):
                logger.warning('Entity unit %d: uncertain prior create; reconcile with app before retry', position)
                continue
            completed = next((r for r in receipts if r['state'] == 'created'), None)
            if completed is not None:
                self._apply(document, unit, completed['entity_id'])
                known.append((source, completed['entity_id']))
                continue
            operation = 'candidate retrieval'
            try:
                candidates = self._candidates(source, known, cache)
                logger.debug('Entity unit %d: %d candidate entities', position, len(candidates))
                operation = 'LLM decision'
                decision = self.match_entity(name, source, candidates)
                if decision.action == 'unresolved' or not decision.source_is_person:
                    logger.debug('Entity unit %d: unresolved', position)
                    continue
                if decision.action == 'select':
                    entity = candidates[decision.item_id]
                else:
                    record = {'state': 'uncertain', 'targets': tuple(targets), 'source': source, 'entity_id': None}
                    pending.append(record)  # Journal before POST: its success may be unknowable.
                    operation = 'entity creation'
                    created = self.db_api_service.create_entity(
                        name=name, aliases=source['aliases'], description=source['description'],
                        short_description=source['short_description'])
                    if (not isinstance(created, dict) or not _text(created.get('entity_id'))
                            or created.get('entity_type', 'person') != 'person'
                            or created.get('name', name) != name):
                        raise ValueError('Invalid create response')
                    entity = {k: source[k] for k in ('name', 'aliases', 'description', 'short_description')}
                    entity.update(entity_type='person', entity_id=created['entity_id'])
                    record.update(state='created', entity_id=entity['entity_id'])
                    logger.debug('Entity unit %d: created an entity', position)
                cache[entity['entity_id']] = entity
                known.append((source, entity['entity_id']))
                operation = 'identity propagation'
                self._apply(document, unit, entity['entity_id'])
            except Exception as exc:
                logger.error('Entity unit %d: %s failed (%s)', position, operation, type(exc).__name__)
                raise RuntimeError(f'Entity matching failed at unit {position}; inspect safe operation diagnostics') from None
        return document

    def process_page(self, page_layout):
        """Retain face-only page callers through the document-wide implementation.

        Args:
            page_layout: Original PeopleGator page, returned after processing.
        """
        document = PeopleGatorDocument(page_layouts=[page_layout])
        if not hasattr(page_layout, '_entity_linking_journal'):
            page_layout._entity_linking_journal = []
        document.entity_linking_journal = page_layout._entity_linking_journal
        self.process_document(document)
        return page_layout

    def _candidates(self, source, known, cache):
        """Retrieve and hydrate unique candidates; failures never become zero hits.

        Args:
            source: Source names, aliases and contextual facts.
            known: Earlier resolved/created source records and protected IDs.
            cache: Validated app records already read during this run.
        """
        queries = _strings([source['name'], *source['aliases'], *source['descriptions']])
        response = self.db_api_service.search_entities(query=queries)
        if not isinstance(response, dict) or not isinstance(response.get('items'), list):
            raise ValueError('Invalid search response')
        ids = []
        for hit in response['items']:
            if not isinstance(hit, dict) or not _text(hit.get('entity_id')):
                raise ValueError('Invalid search hit')
            ids.append(hit['entity_id'])
        names = _name_keys([source['name'], *source['aliases']])
        ids.extend(entity_id for previous, entity_id in known
                   if names & _name_keys([previous['name'], *previous['aliases']]))
        result = []
        for entity_id in dict.fromkeys(ids):
            if entity_id not in cache:
                detail = self.db_api_service.get_entity_info(entity_id)
                if (not isinstance(detail, dict) or detail.get('entity_id') != entity_id
                        or not _text(detail.get('name')) or not _text(detail.get('entity_type'))
                        or not isinstance(detail.get('aliases', []), (list, type(None)))
                        or any(not isinstance(a, str) for a in (detail.get('aliases') or []))
                        or any(detail.get(k) is not None and not isinstance(detail[k], str)
                               for k in ('description', 'short_description'))):
                    raise ValueError('Invalid candidate detail')
                cache[entity_id] = {k: detail.get(k) for k in
                                    ('entity_id', 'entity_type', 'name', 'aliases', 'description', 'short_description')}
            result.append(cache[entity_id])
        return result

    def match_entity(self, name, caption, db_entities):
        """Validate typed decisions and require grounded contextual comparisons.

        Args:
            name: Canonical source proposal.
            caption: Source evidence mapping, or caption string for legacy callers.
            db_entities: Hydrated app candidates in request-local order.

        Returns:
            A validated explicit decision; invalid decisions raise safely.
        """
        source = caption if isinstance(caption, dict) else {'captions': [caption] if caption else []}
        entities = self.prepare_entities(db_entities)
        result = self.llm_prompter(data={'name': name, 'context': source, 'entities': entities},
                                   response_model=EntityMatchingResult)
        try:
            result = EntityMatchingResult.model_validate(result)
        except ValidationError:
            raise ValueError('Invalid entity decision') from None
        if result.action == 'unresolved':
            return result
        if not result.source_is_person:
            raise ValueError('Non-person decision cannot link or create')
        facts = _strings([*source.get('descriptions', []), *source.get('captions', []),
                          *(s['context'] for s in source.get('sources', []))])
        supported = set()
        for evidence in result.evidence:
            index = evidence.item_id
            if not 0 <= index < len(entities):
                raise ValueError('Evidence candidate is outside request')
            candidate = entities[index]
            candidate_facts = _strings([candidate.get('description'), candidate.get('short_description')])
            if (not _text(evidence.source_quote) or not _text(evidence.candidate_quote)
                    or not any(evidence.source_quote in text for text in facts)
                    or not any(evidence.candidate_quote in text for text in candidate_facts)
                    or _name_only(evidence.source_quote, [name, *source.get('aliases', [])])
                    or _name_only(evidence.candidate_quote, [candidate['name'], *(candidate.get('aliases') or [])])):
                raise ValueError('Decision lacks grounded contextual evidence')
            if (result.action == 'create'
                    and _name_keys([evidence.source_quote]) == _name_keys([evidence.candidate_quote])):
                raise ValueError('Identical evidence does not justify a different being')
            supported.add(index)
        if result.action == 'select':
            index = result.item_id
            if (index is None or not 0 <= index < len(entities) or supported != {index}
                    or result.name != entities[index]['name'] or entities[index]['entity_type'] != 'person'):
                raise ValueError('Invalid candidate selection')
        elif (result.item_id is not None or result.name != name or supported != set(range(len(entities)))):
            raise ValueError('Create requires affirmative differences from every candidate')
        return result

    @staticmethod
    def prepare_entities(db_entities):
        """Return candidate copies with trusted zero-based request indices.

        Args:
            db_entities: Hydrated app records; retrieval scores are excluded.
        """
        return [dict(entity, item_id=index) for index, entity in enumerate(db_entities)]

    @staticmethod
    def _apply(document, unit, entity_id):
        """Apply one successful app ID while retaining local objects and metadata.

        Args:
            document: Original document for page-local identity allocation.
            unit: Explicitly or contextually reconciled original references.
            entity_id: Successfully resolved/created app identifier.
        """
        for identity in unit.identities():
            if identity.peoplegator_id is None:
                identity.peoplegator_id = entity_id
        for cluster in unit.clusters:
            if cluster.identity is None:
                cluster.identity = PeopleGatorIdentity(cluster.name or next(
                    (m.proposed_name or m.name for m in cluster.text_entities), None), entity_id)
        document.distribute_text_entity_identities(clusters=unit.clusters)
