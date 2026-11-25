"""Save engine results and load trusted local checkpoints."""

import json
from pathlib import Path
import pickle


def save_checkpoint(path, document, metadata):
    """Write the complete document followed by its JSON metadata.

    Args:
        path: New stage directory.
        document: Document returned by the completed engine.
        metadata: JSON-serializable dictionary supplied by the caller.
    """
    stage = Path(path)
    stage.mkdir(mode=0o700, parents=True)
    with (stage / 'document.pkl').open('wb') as stream:
        pickle.dump(document, stream)
    with (stage / 'checkpoint.json').open('w', encoding='utf-8') as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2)


def load_checkpoint(path):
    """Return the document and metadata. Load only trusted files: Pickle can execute code.

    Args:
        path: Stage directory or its checkpoint.json.
    """
    marker = Path(path)
    if marker.is_dir():
        marker = marker / 'checkpoint.json'
    with marker.open(encoding='utf-8') as stream:
        metadata = json.load(stream)
    with (marker.parent / 'document.pkl').open('rb') as stream:
        document = pickle.load(stream)
    return document, metadata
