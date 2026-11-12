"""Read-only, selected JSON diagnostics for trusted hybrid checkpoints."""

from configparser import ConfigParser
from dataclasses import asdict


def document_summary(document):
    """Return compact per-stage result counts without duplicating document state.

    Args:
        document: Post-engine or restored document.
    """
    pages = document.page_layouts
    regions = [region for page in pages for region in page.regions]
    identities = {id(identity): identity for identity in
                  [cluster.identity for cluster in document.text_entity_clusters] +
                  [getattr(getattr(mention, 'page_identity', None), 'identity', None) for mention in document.text_entities] +
                  [getattr(getattr(face.face_metadata, 'page_identity', None), 'identity', None) for face in document.faces]
                  if identity is not None}
    return {'pages': len(pages), 'text_regions': sum(region.category in (None, 'text') for region in regions),
            'text_lines': sum(len(region.lines) for region in regions),
            'nontext_regions': sum(region.category not in (None, 'text') for region in regions),
            'faces': len(document.faces), 'text_mentions': len(document.text_entities),
            'clusters': len(document.text_entity_clusters),
            'resolved_identities': len({identity.peoplegator_id for identity in identities.values()
                                        if identity.peoplegator_id is not None})}


def _coordinates(value):
    """Convert selected diagnostic geometry, not arbitrary document objects.

    Args:
        value: Numeric array, sequence or None.
    """
    return value.tolist() if hasattr(value, 'tolist') else value


def inspect_checkpoint(path, details=('ocr', 'regions', 'entities')):
    """Export selected details from a trusted local checkpoint without processing.

    Args:
        path: Published stage directory or checkpoint.json, never an external Pickle.
        details: Selected diagnostic groups; these are not a recovery representation.
    """
    from people_gator.core.checkpoints import read_metadata, load_document
    data, marker = read_metadata(path)
    document = load_document(data, marker, ConfigParser())
    result = {'schema_version': data['schema_version'], 'run_id': data['run_id'],
              'last_completed': data['last_completed'], 'next_step': data['next_step'],
              'summary': document_summary(document), 'document': {'id': document.id, 'name': document.name,
              'library': document.library}, 'pages': []}
    mentions = {id(mention): index for index, mention in enumerate(document.text_entities)}
    for page in document.page_layouts:
        record = {'id': page.id, 'page_size': _coordinates(page.page_size)}
        if 'ocr' in details:
            record['ocr'] = [{'region_id': region.id, 'line_id': line.id, 'text': line.transcription,
                'polygon': _coordinates(line.polygon), 'baseline': _coordinates(line.baseline),
                'heights': _coordinates(line.heights), 'confidence': float(line.transcription_confidence)
                if line.transcription_confidence is not None else None}
                for region in page.regions for line in region.lines]
        if 'regions' in details:
            record['regions'] = [{'id': region.id, 'category': region.category, 'type': region.region_type,
                'polygon': _coordinates(region.polygon), 'confidence': float(region.detection_confidence)
                if region.detection_confidence is not None else None,
                'source_region_id': getattr(getattr(region, 'source_region', None), 'id', None)} for region in page.regions]
            record['faces'] = []
            for face in page.faces:
                metadata = face.face_metadata
                identity = getattr(getattr(metadata, 'page_identity', None), 'identity', None)
                landmarks = {}
                for key in ('left_eye_position', 'right_eye_position', 'nose_position',
                            'left_mouth_corner_position', 'right_mouth_corner_position'):
                    position = getattr(metadata, key, None)
                    landmarks[key] = {'x': _coordinates(position.x), 'y': _coordinates(position.y)} if position else None
                record['faces'].append({'id': face.id, 'name': getattr(identity, 'name', None),
                    'entity_id': getattr(identity, 'peoplegator_id', None), 'landmarks': landmarks,
                    'source_region_id': getattr(face.source_region, 'id', None)})
        if 'entities' in details:
            record['mentions'] = [{'index': mentions[id(mention)], 'name': mention.name, 'text': mention.text,
                'proposed_name': mention.proposed_name, 'description': mention.description,
                'source_spans': [asdict(span) for span in mention.source_spans],
                'entity_id': getattr(getattr(mention.page_identity, 'identity', None), 'peoplegator_id', None)}
                for mention in page.text_entities]
        result['pages'].append(record)
    if 'entities' in details:
        result['clusters'] = [{'name': cluster.name, 'description': cluster.description,
            'mentions': [mentions[id(mention)] for mention in cluster.text_entities],
            'entity_id': getattr(cluster.identity, 'peoplegator_id', None)} for cluster in document.text_entity_clusters]
    return result
