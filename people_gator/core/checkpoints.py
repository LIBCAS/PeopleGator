"""Versioned processing snapshots, compatibility checks and durable replay guards."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4, UUID

from people_gator.core.checkpoint_document import (
    CheckpointError, PROTOCOL, compatibility_identity, serialize_document, restore_document,
)

SCHEMA_VERSION = 2
_SECRET = re.compile(r'api.?key|password|passwd|(?:^|[_-])token(?:$|[_-])|secret|credential|authorization|private.?key', re.I)
_PORTABLE = {'processing_checkpoints', 'input_image_path',
             'input_xml_path', 'input_alto_path', 'input_metadata_path',
             'output_xml_path', 'output_alto_path', 'output_render_path',
             'export_to_app', 'drop_existing_annotations'}


def _timestamp():
    """Return an unambiguous UTC checkpoint timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _digest(value):
    """Hash canonical JSON, independently of output formatting.

    Args:
        value: Serializable checkpoint payload.
    """
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, allow_nan=False,
                                     sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _sealed(value):
    """Return a checksummed copy of a durable recovery ledger.

    Args:
        value: Ledger without its checksum.
    """
    return dict(value, integrity_sha256=_digest(value))


def file_identity(path):
    """Return a streaming content hash and size without logging source paths.

    Args:
        path: Required external file.
    """
    try:
        digest = hashlib.sha256()
        size = 0
        with open(path, 'rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
                size += len(block)
        return {'sha256': digest.hexdigest(), 'size': size}
    except OSError:
        raise CheckpointError('Required checkpoint input/resource is missing or unreadable; restore its configured file') from None


def configuration_identity(config, config_dir):
    """Capture ordered effective settings, redacting credentials and hashing resources.

    Args:
        config: Effective ConfigParser, after CLI overrides.
        config_dir: Base directory used by engine resource resolution.
    """
    secrets = [v for section in config.sections() for k, v in config[section].items()
               if _SECRET.search(k) and v]
    sections = []
    for section in config.sections():
        settings = {}
        for key, value in config[section].items():
            key = key.lower()
            if _SECRET.search(key):
                settings[key] = {'credential_required': bool(value)}
            else:
                if any(secret in value for secret in secrets):
                    raise CheckpointError('Credential embedded in a non-credential setting; use separate credential options')
                # URLs carrying credentials cannot be safely retained as settings.
                if re.search(r'://[^/]*@|[?&](?:key|token|password|secret)=', value, re.I):
                    raise CheckpointError('Credentials in resource/service URLs are unsupported; use credential options')
                if section.startswith('ENGINE_') and key.endswith('_path') and value.strip():
                    path = Path(value)
                    if not path.is_absolute():
                        path = Path(config_dir or os.curdir) / path
                    settings[key] = {'resource': file_identity(path)}
                else:
                    settings[key] = value
        sections.append({'section': section, 'settings': settings})
    return sections


def pipeline_manifest(config, identity):
    """Retain exact section name, ordinal, method and non-secret configuration identity.

    Args:
        config: Effective pipeline configuration.
        identity: Sanitized ordered configuration.
    """
    stages = []
    for section in identity:
        name = section['section']
        if name.startswith('ENGINE_'):
            method = config[name].get('METHOD', '').strip()
            if not method:
                raise CheckpointError('Every checkpointed ENGINE section requires a supported METHOD')
            stages.append({'ordinal': len(stages), 'section': name, 'method': method,
                           'configuration_sha256': _digest(section['settings'])})
    return stages


def _comparable(identity):
    """Remove documented machine-specific input/output options for comparison.

    Args:
        identity: Sanitized configuration section list.
    """
    return [dict(section=section['section'], settings={k: v for k, v in section['settings'].items()
            if section['section'] != 'PARSE_FOLDER' or k not in _PORTABLE})
            for section in identity if section['section'] != 'PARSE_FOLDER' or
            any(k not in _PORTABLE for k in section['settings'])]


def input_assets(document):
    """Identify required images/XML/metadata while keeping layout state in JSON.

    Args:
        document: Loaded, possibly processed document.
    """
    assets = []
    for field in ('page_images_dir', 'page_xmls_dir', 'alto_xmls_dir', 'metadata_path'):
        value = getattr(document, field)
        if not value:
            continue
        path = Path(value).resolve()
        if field == 'metadata_path':
            files = [('', path)]
        else:
            if not path.is_dir():
                raise CheckpointError('Required checkpoint input directory is missing')
            if field == 'page_images_dir':
                names = dict.fromkeys(str(p.id) if str(p.id).endswith('.jpg') else str(p.id) + '.jpg'
                                      for p in document.page_layouts)
            else:
                names = sorted(p.name for p in path.iterdir() if p.suffix.lower() == '.xml')
            if any(Path(name).name != name for name in names):
                raise CheckpointError('Checkpoint page identifiers must resolve inside the input directory')
            files = [(name, path / name) for name in names]
        assets.append({'field': field, 'path': str(path), 'files': [
            {'name': name, **file_identity(file)} for name, file in files]})
    return assets


def validate_assets(assets, document, config, relocate=True):
    """Verify exact input content, optionally at current machine-specific paths.

    Args:
        assets: Original input integrity manifest.
        document: Restored document whose source paths can be relocated.
        config: Current configuration supplying replacement paths.
        relocate: Whether to apply current paths to the restored document.
    """
    keys = {'page_images_dir': 'INPUT_IMAGE_PATH', 'page_xmls_dir': 'INPUT_XML_PATH',
            'alto_xmls_dir': 'INPUT_ALTO_PATH', 'metadata_path': 'INPUT_METADATA_PATH'}
    folder = config['PARSE_FOLDER'] if config.has_section('PARSE_FOLDER') else {}
    if document is not None and [a['field'] for a in assets] != [field for field in keys if getattr(document, field)]:
        raise CheckpointError('Incomplete checkpoint input manifest')
    paths = {}
    for asset in assets:
        field = asset['field']
        if field not in keys:
            raise CheckpointError('Invalid checkpoint input manifest')
        value = folder.get(keys[field], folder.get(keys[field].lower(), '')) or asset['path']
        path = Path(value).resolve()
        if field != 'metadata_path' and not path.is_dir():
            raise CheckpointError('Required checkpoint input directory is missing')
        for item in asset['files']:
            name = item['name']
            if name and Path(name).name != name:
                raise CheckpointError('Invalid checkpoint input filename')
            if file_identity(path / name if name else path) != {k: item[k] for k in ('sha256', 'size')}:
                raise CheckpointError('Checkpoint input changed; restore the original bytes before resuming')
        if field in ('page_xmls_dir', 'alto_xmls_dir'):
            actual = sorted(p.name for p in path.iterdir() if p.suffix.lower() == '.xml')
            if actual != [item['name'] for item in asset['files']]:
                raise CheckpointError('Checkpoint XML input set changed')
        paths[field] = str(path)
        if relocate and document is not None:
            setattr(document, field, str(path))
    return paths


def _sync_directory(directory):
    """Persist directory entries where the operating system supports it.

    Args:
        directory: Parent of a newly finalized snapshot.
    """
    if os.name == 'posix':
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_json(path, payload):
    """Flush/sync a private temporary sibling before atomic finalization.

    Args:
        path: New snapshot or replaceable private ledger/pointer file.
        payload: Complete JSON payload, validated before writing.
    """
    path = Path(path)
    raw = json.dumps(payload, ensure_ascii=True, allow_nan=False, indent=2)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.checkpoint-', suffix='.tmp', dir=path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
        _sync_directory(path.parent)
    except OSError:
        raise CheckpointError('Checkpoint write failed; retain the last valid snapshot and run ledger') from None
    finally:
        if temporary is not None:
            os.unlink(temporary)


def _read_json(path):
    """Read strict JSON without echoing damaged/private contents.

    Args:
        path: Snapshot or run ledger file.
    """
    try:
        with open(path, encoding='utf-8') as source:
            return json.load(source, parse_constant=_invalid_constant, object_pairs_hook=_unique_keys)
    except CheckpointError:
        raise
    except (OSError, ValueError, TypeError, RecursionError):
        raise CheckpointError('Checkpoint/ledger is missing, unreadable or malformed; select a finalized snapshot') from None


def _invalid_constant(value):
    """Reject non-JSON numeric constants.

    Args:
        value: Parser constant, intentionally omitted from diagnostics.
    """
    raise CheckpointError('Non-JSON constant in checkpoint')


def _unique_keys(pairs):
    """Reject ambiguous duplicate object keys.

    Args:
        pairs: Ordered JSON key/value pairs.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise CheckpointError('Duplicate JSON key in checkpoint')
        result[key] = value
    return result


@contextmanager
def _run_lock(path):
    """Hold a process lock, released by the OS even after an abrupt crash.

    Args:
        path: Private lock file beside the durable run ledger.
    """
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        raise CheckpointError('Checkpoint run lock is unavailable; restore access to the original history') from None
    try:
        try:
            if os.name == 'posix':
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt
                os.write(fd, b'0')
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            raise CheckpointError('Checkpoint run is already active; concurrent resume is unsafe') from None
        yield
    finally:
        os.close(fd)


class CheckpointRun:
    """One immutable initial configuration/history, with append-only snapshots."""

    def __init__(self, config, config_dir, directory, options, document=None, resume=None):
        """Create a history or validate a resume before any import/engine/export.

        Args:
            config: Effective current configuration, supplying credentials again.
            config_dir: Directory for relative engine resources.
            directory: Snapshot destination, or None to disable resumed snapshots.
            options: Effective app import/export/drop flags.
            document: Initial document, absent when resuming.
            resume: Explicit finalized snapshot path, or None for a new run.
        """
        self.config = config
        self.directory = Path(directory).resolve() if directory else None
        self.current_configuration = configuration_identity(config, config_dir)
        self.pipeline = pipeline_manifest(config, self.current_configuration)
        self.options = options
        self.completed = []
        self.attempt_id = str(uuid4())
        self.parent_checkpoint = None
        if resume:
            self._restore(resume, expected_document=document)
        else:
            self.document = document
            self.run_id = str(uuid4())
            self.document_id = str(uuid4())
            self.initial_configuration = self.current_configuration
            self.initial_options = dict(options)
            self.assets = input_assets(document)
            # Preflight unsupported fields before expensive/external engine work.
            serialize_document(document, self._secrets())
            self.run_directory = self.directory / self.document_id / self.run_id
            self.run_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
            # pathlib parents use the default umask; privatize our document folder.
            self.run_directory.parent.chmod(0o700)
            self.ledger_path = self.run_directory / 'run-state.json'
            atomic_json(self.ledger_path, _sealed({'schema_version': SCHEMA_VERSION, 'run_id': self.run_id,
                'document_id': self.document_id, 'side_effect_step': -1, 'export_attempted': False, 'checkpoints': {}}))
        self._check_receipts(self.document)

    @staticmethod
    def _check_receipts(document):
        """Stop checkpoint recovery with unresolved original creation receipts.

        Args:
            document: Complete document carrying original linking receipts.
        """
        journal = document.entity_linking_journal
        if (not isinstance(journal, list) or any(not isinstance(record, dict)
                or record.get('state') not in {'uncertain', 'created'}
                or not {'state', 'targets', 'source', 'entity_id'} <= record.keys()
                for record in journal)):
            raise CheckpointError('Invalid checkpoint entity creation journal')
        if any(record['state'] == 'uncertain' for record in journal):
            raise CheckpointError('Uncertain entity creation receipt; manual reconciliation with PeopleGatorApp is required')

    def _secrets(self):
        """Collect credentials for private-state checks without persisting them."""
        return [v for section in self.config.sections() for k, v in self.config[section].items()
                if _SECRET.search(k) and v]

    def _restore(self, path, expected_document=None):
        """Validate metadata/configuration before unpickling a trusted local payload.

        Args:
            path: Published stage directory or checkpoint.json.
            expected_document: Optional caller-supplied logical document identity.
        """
        data, marker = read_metadata(path)
        if expected_document is not None and [expected_document.id, expected_document.library] != data['document_identity']:
            raise CheckpointError('Checkpoint belongs to a different document')
        if data['pipeline'] != self.pipeline or _comparable(data['initial_configuration']) != _comparable(self.current_configuration):
            raise CheckpointError('Checkpoint pipeline/configuration/resource changed; restore the initial configuration')
        self.initial_options = data['initial_options']
        if self.options['device'] != self.initial_options['device']:
            raise CheckpointError('Checkpoint processing device changed; use the original device selection')
        if self.options['import_from_app'] != self.initial_options['import_from_app']:
            raise CheckpointError('Checkpoint import baseline changed; keep its original import setting (import will be skipped)')
        self.document = load_document(data, marker, self.config)
        self.completed = data['completed_steps']
        self.run_id = data['run_id']
        self.document_id = data['document_id']
        self.initial_configuration = data['initial_configuration']
        self.assets = data['input_assets']
        self.run_directory = Path(data['run_directory'])
        self.ledger_path = self.run_directory / 'run-state.json'
        self.parent_checkpoint = str(marker)

    @contextmanager
    def locked(self):
        """Validate durable side effects while holding the run's exclusive lock."""
        if not self.run_directory.is_dir():
            raise CheckpointError('Original run ledger is required; restore the checkpoint history directory')
        with _run_lock(self.run_directory / '.lock'):
            ledger = read_ledger(self.run_directory, self.run_id, self.document_id)
            if ledger['side_effect_step'] >= len(self.completed):
                raise CheckpointError('Possible app writes after this checkpoint; use a later completed snapshot or reconcile manually with PeopleGatorApp before a new run')
            if self.options['export_to_app'] and ledger['export_attempted']:
                raise CheckpointError('App export was already attempted; manual reconciliation is required before another export')
            self.ledger = ledger
            yield self

    def before_engine(self, ordinal):
        """Durably fence possible external mutations before ENTITY_MATCHING runs.

        Args:
            ordinal: Zero-based stage index.
        """
        if self.pipeline[ordinal]['method'] == 'ENTITY_MATCHING':
            self.ledger['side_effect_step'] = ordinal
            atomic_json(self.ledger_path, _sealed(self.ledger))

    def before_export(self):
        """Fence every export attempt, even successful or partially failed ones."""
        self.ledger['export_attempted'] = True
        atomic_json(self.ledger_path, _sealed(self.ledger))

    def save(self, document, ordinal, duration):
        """Save exactly the returned post-engine state before recording completion.

        Args:
            document: Successful engine result.
            ordinal: Completed stage index.
            duration: Engine elapsed seconds, excluding checkpoint I/O.
        """
        record = dict(self.pipeline[ordinal], status='completed', finished_at=_timestamp(), duration_seconds=duration)
        self._check_receipts(document)
        completed = self.completed + [record]
        if self.directory:
            from people_gator.core.checkpoint_inspection import document_summary
            validate_assets(self.assets, document, self.config, relocate=False)
            payload = serialize_document(document, self._secrets())
            destination = self.directory / self.document_id / self.run_id / self.attempt_id
            destination.mkdir(mode=0o700, parents=True, exist_ok=True)
            destination.parent.chmod(0o700)
            destination.parent.parent.chmod(0o700)
            section = re.sub(r'[^a-zA-Z0-9_-]', '_', record['section'])[:80]
            stage = destination / f'{ordinal + 1:04d}-{section}'
            stage.mkdir(mode=0o700, exist_ok=False)
            # Payload first. A directory without checkpoint.json is never resumable.
            atomic_payload(stage / 'document.pkl', payload)
            data = {'schema_version': SCHEMA_VERSION, 'run_id': self.run_id, 'document_id': self.document_id,
                    'attempt_id': self.attempt_id, 'created_at': _timestamp(),
                    'document_identity': [document.id, document.library],
                    'run_directory': str(self.run_directory), 'parent_checkpoint': self.parent_checkpoint,
                    'compatibility': compatibility_identity(), 'pipeline': self.pipeline,
                    'initial_configuration': self.initial_configuration,
                    'execution_configuration': self.current_configuration, 'initial_options': self.initial_options,
                    'input_assets': self.assets, 'completed_steps': completed,
                    'last_completed': ordinal, 'next_step': ordinal + 1,
                    'summary': document_summary(document),
                    'payload': {'filename': 'document.pkl', 'size': len(payload),
                                'sha256': hashlib.sha256(payload).hexdigest(), 'protocol': PROTOCOL}}
            data['integrity_sha256'] = _digest(data)
            raw = json.dumps(data, ensure_ascii=True)
            if any(json.dumps(secret, ensure_ascii=True)[1:-1] in raw for secret in self._secrets()):
                raise CheckpointError('Credential found in checkpoint metadata')
            marker = stage / 'checkpoint.json'
            # Register provenance durably, then publish the JSON commit marker last.
            self.ledger['checkpoints'][str(marker)] = data['integrity_sha256']
            atomic_json(self.ledger_path, _sealed(self.ledger))
            atomic_json(marker, data)
            atomic_json(self.run_directory / 'latest.json', {'checkpoint': str(marker)})
            self.parent_checkpoint = str(marker)
        self.completed = completed
        self.document = document


def atomic_payload(path, payload):
    """Flush/sync and finalize the Pickle before a JSON commit marker can exist.

    Args:
        path: New stage payload path.
        payload: Locally generated and round-trip-validated Pickle bytes.
    """
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.document-', suffix='.tmp', dir=Path(path).parent)
        with os.fdopen(fd, 'wb') as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
        _sync_directory(Path(path).parent)
    except OSError:
        raise CheckpointError('Checkpoint payload write failed; retain the previous completed checkpoint') from None
    finally:
        if temporary is not None:
            os.unlink(temporary)


def _protected(path, directory=False):
    """Require protected local checkpoint files; checksums do not establish trust.

    Args:
        path: Locally generated file or stage/history directory.
        directory: Whether the path must be a directory.
    """
    try:
        path = Path(path)
        if path.is_symlink() or (not path.is_dir() if directory else not path.is_file()):
            raise CheckpointError('Checkpoint requires its original protected local files')
        stat = path.stat()
        if os.name == 'posix' and (stat.st_uid != os.geteuid() or stat.st_mode & 0o077):
            raise CheckpointError('Checkpoint files must be private and owned by the current user before trusted loading')
    except OSError:
        raise CheckpointError('Checkpoint protected local files are missing or inaccessible') from None


def read_ledger(directory, run_id, document_id):
    """Validate the original private run ledger and local publication registry.

    Args:
        directory: Original history directory.
        run_id: Expected run UUID.
        document_id: Expected document storage UUID.
    """
    _protected(directory, directory=True)
    path = Path(directory) / 'run-state.json'
    _protected(path)
    ledger = _read_json(path)
    if not isinstance(ledger, dict):
        raise CheckpointError('Invalid checkpoint run ledger')
    integrity = ledger.pop('integrity_sha256', None)
    if integrity != _digest(ledger):
        raise CheckpointError('Checkpoint run ledger integrity mismatch; restore the intact history before recovery')
    if (type(ledger.get('schema_version')) is not int or ledger['schema_version'] != SCHEMA_VERSION
            or ledger.get('run_id') != run_id or ledger.get('document_id') != document_id
            or type(ledger.get('side_effect_step')) is not int or ledger['side_effect_step'] < -1
            or type(ledger.get('export_attempted')) is not bool or not isinstance(ledger.get('checkpoints'), dict)):
        raise CheckpointError('Invalid checkpoint run ledger')
    return ledger


def read_metadata(path):
    """Validate manifest, environment and local provenance WITHOUT unpickling.

    Args:
        path: Trusted local stage directory or its checkpoint.json marker.
    """
    try:
        path = Path(path)
        marker = path / 'checkpoint.json' if path.is_dir() else path
        if marker.name != 'checkpoint.json':
            raise CheckpointError('Resume requires a finalized checkpoint directory or checkpoint.json')
        _protected(marker)
        for directory in (marker.parent, marker.parent.parent, marker.parent.parent.parent):
            _protected(directory, directory=True)
        marker = marker.resolve()
        data = _read_json(marker)
        if type(data.get('schema_version')) is not int or data['schema_version'] != SCHEMA_VERSION:
            raise CheckpointError('Unsupported checkpoint schema_version; old JSON-only snapshots cannot resume here')
        required = {'schema_version', 'run_id', 'document_id', 'attempt_id', 'created_at', 'document_identity',
                    'run_directory', 'parent_checkpoint', 'compatibility', 'pipeline', 'initial_configuration',
                    'execution_configuration', 'initial_options', 'input_assets', 'completed_steps',
                    'last_completed', 'next_step', 'summary', 'payload', 'integrity_sha256'}
        if set(data) != required:
            raise CheckpointError('Malformed or incomplete checkpoint manifest fields')
        options = data['initial_options']
        summary_keys = {'pages', 'text_regions', 'text_lines', 'nontext_regions', 'faces',
                        'text_mentions', 'clusters', 'resolved_identities'}
        if (set(options) != {'device', 'import_from_app', 'export_to_app', 'drop_existing_annotations'}
                or not isinstance(options['device'], str) or any(type(options[key]) is not bool for key in
                ('import_from_app', 'export_to_app', 'drop_existing_annotations'))
                or not isinstance(data['summary'], dict) or set(data['summary']) != summary_keys
                or any(type(value) is not int or value < 0 for value in data['summary'].values())):
            raise CheckpointError('Malformed checkpoint options/summary')
        integrity = data.pop('integrity_sha256')
        if _digest(data) != integrity:
            raise CheckpointError('Checkpoint integrity mismatch; select an intact checkpoint')
        for key in ('run_id', 'document_id', 'attempt_id'):
            UUID(data[key])
        datetime.fromisoformat(data['created_at'])
        if data['compatibility'] != compatibility_identity():
            raise CheckpointError('Checkpoint Python/Pickle/package/code compatibility changed; use the original environment')
        payload = data['payload']
        if (payload['filename'] != 'document.pkl' or type(payload['protocol']) is not int
                or payload['protocol'] != PROTOCOL or type(payload['size']) is not int or payload['size'] < 2
                or not re.fullmatch('[0-9a-f]{64}', payload['sha256'])):
            raise CheckpointError('Unsupported or malformed Pickle payload metadata')
        stages = data['pipeline']
        expected = []
        for section in data['initial_configuration']:
            if section['section'].startswith('ENGINE_'):
                expected.append({'ordinal': len(expected), 'section': section['section'],
                    'method': section['settings']['method'], 'configuration_sha256': _digest(section['settings'])})
        if stages != expected:
            raise CheckpointError('Invalid checkpoint pipeline identity')
        completed = data['completed_steps']
        if not completed or len(completed) > len(stages):
            raise CheckpointError('Invalid checkpoint completion history')
        for index, record in enumerate(completed):
            if ({k: record[k] for k in stages[index]} != stages[index] or type(record['ordinal']) is not int
                    or record['status'] != 'completed' or type(record['duration_seconds']) not in (int, float)
                    or record['duration_seconds'] < 0):
                raise CheckpointError('Checkpoint completed stages must be an ordered pipeline prefix')
            datetime.fromisoformat(record['finished_at'])
        if (type(data['next_step']) is not int or type(data['last_completed']) is not int
                or data['next_step'] != len(completed) or data['last_completed'] != len(completed) - 1):
            raise CheckpointError('Inconsistent checkpoint next stage')
        if not isinstance(data['document_identity'], list) or len(data['document_identity']) != 2:
            raise CheckpointError('Invalid checkpoint document identity')
        ledger = read_ledger(Path(data['run_directory']), data['run_id'], data['document_id'])
        if ledger['checkpoints'].get(str(marker)) != integrity:
            raise CheckpointError('Checkpoint was not published in this trusted local history; never load externally supplied Pickle files')
        if ledger['side_effect_step'] >= len(stages):
            raise CheckpointError('Invalid checkpoint run ledger stage')
        return data, marker
    except CheckpointError:
        raise
    except Exception:
        raise CheckpointError('Malformed or incomplete checkpoint manifest') from None


def load_document(data, marker, config):
    """Verify external inputs and the exact payload bytes before trusted unpickling.

    Args:
        data: Validated JSON metadata.
        marker: Validated local JSON commit marker path.
        config: Current configuration for compatible machine-specific input paths.
    """
    try:
        paths = validate_assets(data['input_assets'], None, config)
        payload_path = marker.parent / 'document.pkl'
        _protected(payload_path)
        payload = payload_path.read_bytes()
        if (len(payload) != data['payload']['size'] or hashlib.sha256(payload).hexdigest() != data['payload']['sha256']):
            raise CheckpointError('Checkpoint Pickle payload size/checksum mismatch')
        if payload[:2] != bytes((0x80, PROTOCOL)):
            raise CheckpointError('Unsupported Pickle protocol in checkpoint payload')
        document = restore_document(payload, paths.get('page_images_dir'))
        if [document.id, document.library] != data['document_identity']:
            raise CheckpointError('Checkpoint document identity mismatch')
        validate_assets(data['input_assets'], document, config)
        return document
    except CheckpointError:
        raise
    except Exception:
        raise CheckpointError('Checkpoint document or required inputs are missing, corrupt or incompatible') from None
