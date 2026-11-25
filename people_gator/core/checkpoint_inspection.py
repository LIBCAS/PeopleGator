"""Read-only, selected JSON diagnostics for trusted local checkpoints."""

from dataclasses import asdict

from people_gator.core.checkpoints import load_checkpoint


def document_summary(document):
    """Return compact per-stage result counts without duplicating document state.

    Args:
        document: Post-engine or restored document.
    """
    pages = document.page_layouts
    regions = [region for page in pages for region in page.regions]
    mentions = document.text_entities
    faces = document.faces
    identities = [cluster.identity for cluster in document.text_entity_clusters]
    identities.extend(mention.page_identity.identity for mention in mentions if mention.page_identity is not None)
    identities.extend(face.face_metadata.page_identity.identity for face in faces
                      if face.face_metadata is not None and face.face_metadata.page_identity is not None)
    return {'pages': len(pages), 'text_regions': sum(region.category in (None, 'text') for region in regions),
            'text_lines': sum(len(region.lines) for region in regions),
            'nontext_regions': sum(region.category not in (None, 'text') for region in regions),
            'faces': len(faces), 'text_mentions': len(mentions),
            'clusters': len(document.text_entity_clusters),
            'resolved_identities': len({identity.peoplegator_id for identity in identities
                                        if identity is not None and identity.peoplegator_id is not None})}


def _coordinates(value):
    """Convert selected diagnostic geometry, not arbitrary document objects.

    Args:
        value: Numeric array, sequence or None.
    """
    return value.tolist() if hasattr(value, 'tolist') else value


def inspect_checkpoint(path, details=('ocr', 'regions', 'entities')):
    """Export selected details from a trusted local checkpoint without processing.

    Args:
        path: Trusted stage directory or checkpoint.json. Pickle can execute code.
        details: Selected diagnostic groups; these are not a recovery representation.
    """
    from people_gator.core.layout import PeopleGatorFaceRegionLayout

    document, checkpoint_metadata = load_checkpoint(path)
    result = {**checkpoint_metadata,
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
                'source_region_id': region.source_region.id
                if isinstance(region, PeopleGatorFaceRegionLayout) and region.source_region is not None else None}
                for region in page.regions]
            record['faces'] = []
            for face in page.faces:
                metadata = face.face_metadata
                page_identity = metadata.page_identity if metadata is not None else None
                identity = page_identity.identity if page_identity is not None else None
                positions = {
                    'left_eye_position': metadata.left_eye_position if metadata is not None else None,
                    'right_eye_position': metadata.right_eye_position if metadata is not None else None,
                    'nose_position': metadata.nose_position if metadata is not None else None,
                    'left_mouth_corner_position': metadata.left_mouth_corner_position if metadata is not None else None,
                    'right_mouth_corner_position': metadata.right_mouth_corner_position if metadata is not None else None,
                }
                landmarks = {key: {'x': _coordinates(pos.x), 'y': _coordinates(pos.y)} if pos is not None else None
                             for key, pos in positions.items()}
                record['faces'].append({'id': face.id, 'name': identity.name if identity is not None else None,
                    'entity_id': identity.peoplegator_id if identity is not None else None, 'landmarks': landmarks,
                    'source_region_id': face.source_region.id if face.source_region is not None else None})
        if 'entities' in details:
            record['mentions'] = []
            for mention in page.text_entities:
                identity = mention.page_identity.identity if mention.page_identity is not None else None
                record['mentions'].append({'index': mentions[id(mention)], 'name': mention.name, 'text': mention.text,
                    'proposed_name': mention.proposed_name, 'description': mention.description,
                    'source_spans': [asdict(span) for span in mention.source_spans],
                    'entity_id': identity.peoplegator_id if identity is not None else None})
        result['pages'].append(record)
    if 'entities' in details:
        result['clusters'] = [{'name': cluster.name, 'description': cluster.description,
            'mentions': [mentions[id(mention)] for mention in cluster.text_entities],
            'entity_id': cluster.identity.peoplegator_id if cluster.identity is not None else None}
            for cluster in document.text_entity_clusters]
    return result
