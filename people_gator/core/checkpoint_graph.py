"""Lossless JSON object tables for the audited document model (no pickle/imports).

Every instance attribute is visited, including inherited and extra metadata.
Unknown types fail closed. Class/function names are resolved only against an
explicit registry, never by importing names supplied by a checkpoint.
"""

import base64
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import hashlib
import inspect
import math
from pathlib import Path, PosixPath, WindowsPath
import struct
from uuid import UUID, SafeUUID
import zlib

import numpy as np
from scipy import sparse


class CheckpointError(ValueError):
    """Safe checkpoint diagnostic, containing no document values or file paths."""


_FIELDS = {
    'PeopleGatorDocument': 'id name library page_layouts page_xmls_dir alto_xmls_dir metadata_path source_metadata text_entity_clusters entity_linking_journal page_images page_images_dir load_images keep_images_in_memory',
    'PageLayout': 'id page_size regions reading_order confidence embeddings metadata to_pagexml_started to_pagexml_processing_added to_pagexml_regions_started to_pagexml_regions_ended to_pagexml_ended to_altoxml_started to_altoxml_processing_added to_altoxml_regions_started to_altoxml_regions_ended to_altoxml_ended from_pagexml_started from_pagexml_ended from_altoxml_started from_altoxml_ended',
    'PeopleGatorPageLayout': 'text_entities',
    'RegionLayout': 'id polygon region_type category lines transcription detection_confidence embeddings metadata',
    'TextLine': 'id index baseline polygon heights transcription logits crop characters logit_coords character_confidences transcription_confidence category embeddings metadata',
    'Event': '_handlers',
    'AnnoPageRegionLayout': 'graphical_metadata',
    'BaseMetadata': 'tag_id mods_id mods_uuid record_identifier used_ai_models creation_date_time confidence',
    'GraphicalObjectMetadata': 'tag_description caption topics color description title continuing_line prompts caption_lines_metadata reference_lines_metadata',
    'RelatedLinesMetadata': 'lines relation description title',
    'ColorInfo': 'color_mode dominant_colors',
    'DominantColorInfo': 'name coverage',
    'PeopleGatorIdentity': 'name peoplegator_id other_ids',
    'PeopleGatorPageIdentity': 'identity',
    'PeopleGatorFaceMetadata': 'page_identity left_eye_position right_eye_position nose_position left_mouth_corner_position right_mouth_corner_position',
    'PeopleGatorFaceRegionLayout': 'face_metadata source_region',
    'PeopleGatorTextEntityMention': 'source_spans proposed_name description name text line span page_identity',
    'PeopleGatorTextEntityCluster': 'text_entities identity name description short_description',
    'Position': 'x y',
    'SourceLine': 'page_index page_id region_index region_id line_index line_id',
    'SourceSpan': 'source start end',
}


def _check_fields(cls, fields):
    """Require every audited inherited constructor field without dropping extras.

    Args:
        cls: Explicitly allowed document-model type.
        fields: Actual attribute mapping.
    """
    required = {field for base in cls.__mro__ for field in _FIELDS.get(base.__name__, '').split()}
    if not required <= fields.keys():
        raise CheckpointError('Incomplete checkpoint object; an audited inherited field is missing')


def _registry():
    """Return the explicitly audited classes and XML event handlers."""
    from anno_page.core import layout as anno, metadata
    from anno_page.enums import Category, Language, LineRelation
    from pero_ocr.core import layout as pero
    from people_gator.core import layout
    from people_gator.text import SourceLine, SourceSpan

    classes = [layout.PeopleGatorDocument, layout.PeopleGatorPageLayout,
               layout.PeopleGatorFaceRegionLayout, layout.PeopleGatorFaceMetadata,
               layout.PeopleGatorIdentity, layout.PeopleGatorPageIdentity,
               layout.PeopleGatorTextEntityMention, layout.PeopleGatorTextEntityCluster,
               layout.Position, pero.PageLayout, pero.RegionLayout, pero.TextLine,
               pero.Event, pero.ALTOVersion, pero.PAGEVersion,
               anno.AnnoPagePageLayout, anno.AnnoPageRegionLayout,
               metadata.BaseMetadata, metadata.GraphicalObjectMetadata,
               metadata.RelatedLinesMetadata, metadata.ColorInfo, metadata.DominantColorInfo,
               Category, Language, LineRelation, SourceLine, SourceSpan,
               sparse.csc_matrix, sparse.csr_matrix, sparse.coo_matrix]
    functions = [getattr(module, name) for module in (anno, layout) for name in
                 ('altoxml_load_regions', 'pagexml_load_regions', 'altoxml_add_processing_step',
                  'altoxml_postprocess_lines', 'pagexml_add_processing_step')]
    return {_name(item): item for item in classes + functions}


def _name(item):
    """Return a stable registry key.

    Args:
        item: Audited class or function.
    """
    return item.__module__ + '.' + item.__qualname__


def model_identity():
    """Fingerprint model implementations so changed inherited fields fail closed."""
    modules = {inspect.getmodule(item) for item in _registry().values()}
    return {module.__name__: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in sorted(modules, key=lambda m: m.__name__)}


class GraphEncoder:
    """Encode mutable containers, instances and shared arrays once by reference."""

    def __init__(self):
        """Initialize a document-local object table."""
        self.objects = []
        self.references = {}
        self.registry = _registry()
        self.arrays = []

    def encode(self, value):
        """Return a JSON value or reference, rejecting unsupported populated data.

        Args:
            value: Document object or any of its fields.
        """
        if value is None or type(value) in (bool, int, str):
            return value
        if type(value) is float and math.isfinite(value):
            return value
        previous = self.references.get(id(value))
        if previous is not None:
            return {'ref': previous}
        index = len(self.objects)
        self.references[id(value)] = index
        node = {}
        self.objects.append(node)
        kind = type(value)
        if kind in (list, tuple, set, frozenset):
            node.update(kind=kind.__name__, items=[self.encode(v) for v in value])
        elif kind is dict:
            node.update(kind='dict', items=[[self.encode(k), self.encode(v)] for k, v in value.items()])
        elif kind is np.ndarray:
            if value.dtype.hasobject or value.dtype.fields or value.dtype.metadata:
                raise CheckpointError('Unsupported array dtype; checkpoint cannot preserve this field')
            if any(np.shares_memory(value, other) for other in self.arrays):
                raise CheckpointError('Overlapping array views require an explicit checkpoint adapter')
            self.arrays.append(value)
            node.update(kind='array', dtype=value.dtype.str, shape=list(value.shape),
                        order='F' if value.flags.f_contiguous and not value.flags.c_contiguous else 'C',
                        writable=bool(value.flags.writeable))
            if value.size <= 128 and value.dtype.kind in 'biuf' and value.dtype.itemsize <= 8 and np.isfinite(value).all():
                node['values'] = value.tolist()
            else:
                node['data'] = base64.b64encode(zlib.compress(value.tobytes(order=node['order']))).decode('ascii')
        elif isinstance(value, np.generic):
            if value.dtype.hasobject or value.dtype.fields:
                raise CheckpointError('Unsupported numpy scalar dtype')
            node.update(kind='scalar', dtype=value.dtype.str, data=base64.b64encode(value.tobytes()).decode('ascii'))
        elif isinstance(value, Enum) and self.registry.get(_name(kind)) is kind:
            node.update(kind='enum', type=_name(kind), member=value.name)
        elif kind is datetime:
            if value.tzinfo is not None and type(value.tzinfo) is not timezone:
                raise CheckpointError('Unsupported datetime timezone; add an audited checkpoint adapter')
            node.update(kind='datetime', value=value.isoformat(), fold=value.fold, timezone=self.encode(value.tzinfo))
        elif kind is timezone:
            offset = value.utcoffset(None)
            node.update(kind='timezone', microseconds=(offset.days * 86400 + offset.seconds) * 1000000 + offset.microseconds,
                        name=value.tzname(None))
        elif kind is UUID:
            node.update(kind='UUID', value=str(value), is_safe=value.is_safe.name)
        elif kind in (date, PosixPath, WindowsPath):
            node.update(kind=kind.__name__, value=str(value))
        elif kind in (float, bytes, bytearray):
            node.update(kind=kind.__name__, value=base64.b64encode(
                struct.pack('!d', value) if kind is float else value).decode('ascii'))
        elif inspect.isfunction(value) and self.registry.get(_name(value)) is value:
            node.update(kind='function', type=_name(value))
        elif self.registry.get(_name(kind)) is kind and hasattr(value, '__dict__'):
            _check_fields(kind, vars(value))
            node.update(kind='object', type=_name(kind), fields={})
            for key, field in vars(value).items():
                if not isinstance(key, str) or key.startswith('__'):
                    raise CheckpointError('Unsupported object attribute')
                node['fields'][key] = self.encode(field)
        else:
            raise CheckpointError('Unsupported populated document field; add an audited checkpoint adapter')
        return {'ref': index}

    def document(self, document):
        """Return the whole object table rooted at the supplied document.

        Args:
            document: PeopleGatorDocument to snapshot.
        """
        root = self.encode(document)
        return {'root': root, 'objects': self.objects}


class GraphDecoder:
    """Reconstruct original references without constructors or XML re-import."""

    def __init__(self, graph):
        """Allocate shells before filling links, allowing ordinary object cycles.

        Args:
            graph: JSON object table from GraphEncoder.
        """
        self.nodes = graph['objects']
        self.registry = _registry()
        self.values = {}
        self.building = set()
        self.filled = set()
        for index, node in enumerate(self.nodes):
            kind = node['kind']
            if kind in ('list', 'dict', 'set'):
                self.values[index] = {'list': list, 'dict': dict, 'set': set}[kind]()
            elif kind == 'object':
                cls = self.registry[node['type']]
                if not inspect.isclass(cls) or issubclass(cls, Enum):
                    raise CheckpointError('Invalid checkpoint object type')
                _check_fields(cls, node['fields'])
                self.values[index] = object.__new__(cls)

    def decode(self, value):
        """Resolve a scalar or reference; never execute checkpoint-provided code.

        Args:
            value: JSON scalar or an object-table reference.
        """
        if value is None or type(value) in (bool, int, str, float):
            return value
        if not isinstance(value, dict) or set(value) != {'ref'} or type(value['ref']) is not int:
            raise CheckpointError('Invalid checkpoint reference')
        index = value['ref']
        if not 0 <= index < len(self.nodes):
            raise CheckpointError('Dangling checkpoint reference')
        if index in self.values:
            self._fill(index)
            return self.values[index]
        if index in self.building:
            raise CheckpointError('Unsupported immutable reference cycle')
        self.building.add(index)
        node = self.nodes[index]
        kind = node['kind']
        if kind in ('tuple', 'frozenset'):
            result = (tuple if kind == 'tuple' else frozenset)(self.decode(v) for v in node['items'])
        elif kind == 'array':
            dtype = np.dtype(node['dtype'])
            if dtype.hasobject or dtype.fields:
                raise CheckpointError('Invalid checkpoint array dtype')
            if 'values' in node:
                result = np.array(node['values'], dtype=dtype, order=node['order']).reshape(node['shape'])
            else:
                raw = zlib.decompress(base64.b64decode(node['data'], validate=True))
                result = np.frombuffer(raw, dtype=dtype).copy().reshape(node['shape'], order=node['order'])
            result.flags.writeable = node['writable']
        elif kind == 'scalar':
            dtype = np.dtype(node['dtype'])
            if dtype.hasobject or dtype.fields:
                raise CheckpointError('Invalid checkpoint scalar dtype')
            result = np.frombuffer(base64.b64decode(node['data'], validate=True), dtype=dtype)[0]
        elif kind == 'enum':
            cls = self.registry[node['type']]
            if not inspect.isclass(cls) or not issubclass(cls, Enum):
                raise CheckpointError('Invalid checkpoint enum')
            result = cls[node['member']]
        elif kind == 'function':
            result = self.registry[node['type']]
            if not inspect.isfunction(result):
                raise CheckpointError('Invalid checkpoint event handler')
        elif kind == 'datetime':
            result = datetime.fromisoformat(node['value']).replace(tzinfo=self.decode(node['timezone']), fold=node['fold'])
        elif kind == 'timezone':
            result = timezone(timedelta(microseconds=node['microseconds']), node['name'])
        elif kind == 'UUID':
            result = UUID(node['value'], is_safe=SafeUUID[node['is_safe']])
        elif kind == 'date':
            result = date.fromisoformat(node['value'])
        elif kind in ('PosixPath', 'WindowsPath'):
            if kind != type(Path()).__name__:
                raise CheckpointError('Checkpoint metadata path flavor requires the original operating system')
            result = Path(node['value'])
        elif kind in ('bytes', 'bytearray', 'float'):
            result = (struct.unpack('!d', base64.b64decode(node['value'], validate=True))[0] if kind == 'float' else
                      {'bytes': bytes, 'bytearray': bytearray}[kind](base64.b64decode(node['value'], validate=True)))
        else:
            raise CheckpointError('Unknown checkpoint node kind')
        self.values[index] = result
        self.building.remove(index)
        return result

    def _fill(self, index):
        """Fill a shell once, resolving hashable records before dictionary insertion.

        Args:
            index: Mutable container or model node position.
        """
        if index in self.filled or index in self.building:
            return
        self.building.add(index)
        target = self.values[index]
        node = self.nodes[index]
        kind = node['kind']
        if kind == 'list':
            target.extend(self.decode(v) for v in node['items'])
        elif kind == 'set':
            target.update(self.decode(v) for v in node['items'])
        elif kind == 'dict':
            for key, value in node['items']:
                target[self.decode(key)] = self.decode(value)
        elif kind == 'object':
            for key, value in node['fields'].items():
                if not isinstance(key, str) or key.startswith('__'):
                    raise CheckpointError('Invalid checkpoint attribute')
                object.__setattr__(target, key, self.decode(value))
        self.building.remove(index)
        self.filled.add(index)

    def document(self, graph):
        """Fill all shells and validate the root document's required structure.

        Args:
            graph: Complete JSON graph, including its root reference.
        """
        from people_gator.core.layout import PeopleGatorDocument, PeopleGatorPageLayout
        for index, node in enumerate(self.nodes):
            self.decode({'ref': index})
        result = self.decode(graph['root'])
        if type(result) is not PeopleGatorDocument or not set(vars(PeopleGatorDocument())) <= set(vars(result)):
            raise CheckpointError('Incomplete checkpoint document')
        if any(type(p) is not PeopleGatorPageLayout for p in result.page_layouts):
            raise CheckpointError('Invalid checkpoint page')
        return result


def restore_document(graph):
    """Decode a graph and suppress private payloads from malformed-data errors.

    Args:
        graph: JSON document graph.
    """
    try:
        return GraphDecoder(graph).document(graph)
    except CheckpointError:
        raise
    except Exception:
        raise CheckpointError('Malformed or incomplete checkpoint document graph') from None
