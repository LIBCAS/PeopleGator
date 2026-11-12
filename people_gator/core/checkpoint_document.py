"""Pickle complete trusted documents; verify fidelity without a JSON graph codec."""

from datetime import datetime
from enum import Enum
import inspect
from io import BytesIO
from pathlib import Path
import pickle
import struct

import numpy as np

PROTOCOL = 5


class CheckpointError(ValueError):
    """Checkpoint diagnostic that contains no private values or source paths."""


def _attributes(value):
    """Read all instance dictionary and inherited slot state for fidelity checks.

    Args:
        value: Original or restored document object.
    """
    state = dict(vars(value)) if hasattr(value, '__dict__') else {}
    for cls in type(value).__mro__:
        slots = getattr(cls, '__slots__', ())
        for key in (slots,) if isinstance(slots, str) else slots:
            if key in ('__dict__', '__weakref__'):
                continue
            if key.startswith('__') and not key.endswith('__'):
                key = '_' + cls.__name__.lstrip('_') + key
            if hasattr(value, key):
                state[key] = getattr(value, key)
    return state


def _check_state(value, secrets, seen=None):
    """Reject credentials and live clients while visiting the actual object state.

    Args:
        value: Document field, including extra or inherited metadata.
        secrets: Current configured credential strings.
        seen: Already visited object identities for cyclic graphs.
    """
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, (str, bytes, bytearray)):
        if any((secret if isinstance(value, str) else secret.encode()) in value for secret in secrets):
            raise CheckpointError('Credential found in checkpoint document metadata; remove it before checkpointing')
        return
    bases = type(value).__mro__
    if any(cls.__module__.split('.')[0] in {'requests', 'httpx', 'httpcore', 'openai', 'socket', '_socket'}
           or cls.__module__ in {'people_gator.core.db', 'people_gator.core.connector',
                                'people_gator.core.document_parser', 'people_gator.core.llm'}
           or (cls.__module__.startswith('people_gator.engines')
               and cls.__name__ in {'DocumentProcessingEngine', 'LLMBasedEngine'}) for cls in bases):
        raise CheckpointError('Live service/client state cannot be checkpointed; retain only recoverable document data')
    if isinstance(value, dict):
        children = [item for pair in value.items() for item in pair]
    elif isinstance(value, (list, tuple, set, frozenset)):
        children = value
    elif isinstance(value, np.ndarray):
        children = value.flat if value.dtype.kind in 'OUS' else ()
    elif inspect.ismethod(value):
        children = (value.__self__,)
    elif isinstance(value, Enum) or inspect.isfunction(value) or inspect.isclass(value):
        if inspect.isfunction(value) and vars(value):
            raise CheckpointError('Runtime callback attributes require targeted Pickle restoration')
        children = ()
    else:
        children = _attributes(value).values()
    for child in children:
        _check_state(child, secrets, seen)


def _equivalent(left, right, aliases, reverse, arrays):
    """Verify fields and reference relationships after a native Pickle round trip.

    Args:
        left: Original document value.
        right: Restored value.
        aliases: Original-to-restored identity mapping.
        reverse: Restored-to-original identity mapping.
        arrays: Array pairs, used to detect lost shared-memory relationships.
    """
    if type(left) is not type(right):
        raise CheckpointError('Pickle changed a populated document field type')
    if left is None or isinstance(left, (str, int, bool, bytes, Enum, np.generic)):
        if isinstance(left, np.generic):
            same = left.dtype == right.dtype and left.tobytes() == right.tobytes()
        else:
            same = left == right
        if not same:
            raise CheckpointError('Pickle changed a populated document value')
        return
    if isinstance(left, float):
        if struct.pack('!d', left) != struct.pack('!d', right):
            raise CheckpointError('Pickle changed a floating-point document value')
        return
    if inspect.isfunction(left) or inspect.isclass(left):
        if left is not right:
            raise CheckpointError('Pickle changed a document callback')
        return
    if id(left) in aliases:
        if aliases[id(left)] is not right:
            raise CheckpointError('Pickle lost a shared document reference')
        return
    if id(right) in reverse:
        raise CheckpointError('Pickle merged distinct document objects')
    aliases[id(left)] = right
    reverse[id(right)] = left
    if isinstance(left, np.ndarray):
        if (left.dtype != right.dtype or left.shape != right.shape
                or left.flags.writeable != right.flags.writeable):
            raise CheckpointError('Pickle changed an array attribute')
        if left.dtype.metadata != right.dtype.metadata:
            raise CheckpointError('Pickle changed array dtype metadata')
        for previous, restored in arrays:
            if np.shares_memory(left, previous) != np.shares_memory(right, restored):
                raise CheckpointError('Pickle cannot preserve overlapping array views; detach the views before checkpointing')
        arrays.append((left, right))
        if left.dtype.hasobject:
            children = zip(left.flat, right.flat)
        else:
            if left.tobytes() != right.tobytes():
                raise CheckpointError('Pickle changed array data')
            return
    elif isinstance(left, dict):
        if len(left) != len(right):
            raise CheckpointError('Pickle changed document metadata')
        children = [(a, b) for pair_a, pair_b in zip(left.items(), right.items()) for a, b in zip(pair_a, pair_b)]
    elif isinstance(left, (list, tuple)):
        if len(left) != len(right):
            raise CheckpointError('Pickle changed document sequence length')
        children = zip(left, right)
    elif isinstance(left, (set, frozenset)):
        if left != right:
            raise CheckpointError('Pickle cannot verify this populated set field')
        children = [(item, next(other for other in right if item == other)) for item in left]
    elif hasattr(left, '__dict__') or _attributes(left):
        original_state, restored_state = _attributes(left), _attributes(right)
        if original_state.keys() != restored_state.keys():
            raise CheckpointError('Pickle omitted a populated document attribute')
        children = [(value, restored_state[key]) for key, value in original_state.items()]
    else:
        if left != right:
            raise CheckpointError('Pickle cannot verify a populated document field')
        if isinstance(left, datetime) and (left.fold != right.fold or left.tzinfo != right.tzinfo):
            raise CheckpointError('Pickle changed datetime metadata')
        return
    for original, restored in children:
        _equivalent(original, restored, aliases, reverse, arrays)


class DocumentPickler(pickle.Pickler):
    """Use standard Pickle memoization and externalize unchanged cached images."""

    def __init__(self, stream, image_references):
        """Initialize the native Pickler.

        Args:
            stream: Binary payload destination.
            image_references: Array identity to verified image filename.
        """
        super().__init__(stream, protocol=PROTOCOL)
        self.image_references = image_references

    def persistent_id(self, obj):
        """Reference a cached image only when its original file recovers it exactly.

        Args:
            obj: Value being pickled.
        """
        name = self.image_references.get(id(obj))
        return ('page-image', name) if name is not None else None


class DocumentUnpickler(pickle.Unpickler):
    """Load only already-validated, trusted payload bytes and verified image files."""

    def __init__(self, stream, image_directory):
        """Initialize image reference recovery.

        Args:
            stream: Validated payload bytes.
            image_directory: Previously integrity-checked image directory, or None.
        """
        super().__init__(stream)
        self.image_directory = image_directory
        self.images = {}

    def persistent_load(self, reference):
        """Reconstruct an external image once and retain shared references.

        Args:
            reference: Pickle's image reference tuple.
        """
        from people_gator.core.utils import load_image
        if (not isinstance(reference, tuple) or len(reference) != 2 or reference[0] != 'page-image'
                or not isinstance(reference[1], str) or Path(reference[1]).name != reference[1]
                or self.image_directory is None):
            raise CheckpointError('Invalid external image reference in document payload')
        name = reference[1]
        if name not in self.images:
            self.images[name] = load_image(str(Path(self.image_directory) / name))
        return self.images[name]


def restore_document(payload, image_directory=None):
    """Unpickle bytes ONLY after the manifest, provenance and environment checks.

    Args:
        payload: Trusted, verified Pickle bytes; never accept arbitrary external input.
        image_directory: Integrity-checked image directory for external cache references.
    """
    from people_gator.core.layout import PeopleGatorDocument
    try:
        stream = BytesIO(payload)
        result = DocumentUnpickler(stream, image_directory).load()
        if type(result) is not PeopleGatorDocument or stream.read(1):
            raise CheckpointError('Invalid Pickle document payload')
        return result
    except CheckpointError:
        raise
    except Exception:
        raise CheckpointError('Could not restore Pickle document; check for incomplete/corrupt data '
                              'and ensure its classes and required dependencies are available') from None


def serialize_document(document, secrets=()):
    """Serialize all state and verify it before publishing any checkpoint marker.

    Args:
        document: Complete post-engine PeopleGatorDocument.
        secrets: Configured credentials which must never enter the payload.
    """
    from people_gator.core.utils import load_image
    try:
        _check_state(document, secrets)
        references = {}
        if document.page_images_dir:
            allowed = {str(page.id) if str(page.id).endswith('.jpg') else str(page.id) + '.jpg'
                       for page in document.page_layouts}
            for page_id, image in document.page_images.items():
                name = str(page_id) if str(page_id).endswith('.jpg') else str(page_id) + '.jpg'
                if name not in allowed:
                    continue
                original = load_image(str(Path(document.page_images_dir) / name))
                if (type(image) is np.ndarray and image.dtype == original.dtype and image.shape == original.shape
                        and image.flags.writeable and np.array_equal(image, original)):
                    references.setdefault(id(image), name)
        stream = BytesIO()
        DocumentPickler(stream, references).dump(document)
        payload = stream.getvalue()
        if any(secret.encode() in payload for secret in secrets):
            raise CheckpointError('Credential found in checkpoint payload')
        restored = restore_document(payload, document.page_images_dir)
        _equivalent(document, restored, {}, {}, [])
        return payload
    except CheckpointError:
        raise
    except Exception:
        raise CheckpointError('Populated document state cannot be faithfully pickled; inspect callbacks and runtime objects') from None
