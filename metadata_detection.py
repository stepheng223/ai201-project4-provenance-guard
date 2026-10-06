"""Analyze structured provenance metadata, never infer from image pixels."""
from datetime import datetime, timezone

AI_TOOLS = {'chatgpt', 'dall-e', 'dall-e 3', 'midjourney', 'stable diffusion', 'suno', 'udio', 'sora'}
LABELS = {
    'likely_ai': 'Likely AI-generated based on the supplied provenance metadata. This assessment does not inspect the asset itself; the creator can appeal.',
    'likely_human': 'Metadata supports human creation, but the supplied history and declarations do not verify authorship.',
    'uncertain': 'Asset authorship uncertain. The supplied provenance metadata is inconclusive and has not been independently verified.',
}


def parse_timestamp(value):
    if not isinstance(value, str) or len(value) > 100:
        raise ValueError('Timestamp must be an ISO 8601 string with timezone.')
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None or date > datetime.now(timezone.utc):
        raise ValueError('Timestamps must have a timezone and cannot be in the future.')
    return date


def validate_metadata(data):
    if not isinstance(data, dict):
        raise ValueError('metadata must be an object.')
    allowed = {'asset_name', 'media_type', 'declared_origin', 'tools', 'revisions', 'generator'}
    if set(data)-allowed:
        raise ValueError('Unknown metadata field.')
    for key, maximum in [('asset_name', 200), ('media_type', 20), ('declared_origin', 20)]:
        if not isinstance(data.get(key), str) or not data[key].strip() or len(data[key]) > maximum:
            raise ValueError('Invalid metadata ' + key)
    if data['media_type'] not in ('image', 'audio', 'video') or data['declared_origin'] not in ('human', 'ai', 'unknown'):
        raise ValueError('Invalid media_type or declared_origin.')
    tools = data.get('tools', [])
    if not isinstance(tools, list) or len(tools) > 20 or any(not isinstance(t, str) or not t.strip() or len(t) > 100 for t in tools):
        raise ValueError('tools must contain at most 20 nonempty tool names.')
    generator = data.get('generator', '')
    if not isinstance(generator, str) or len(generator) > 100:
        raise ValueError('generator must be a string of at most 100 characters.')
    revisions = data.get('revisions', [])
    if not isinstance(revisions, list) or len(revisions) > 20:
        raise ValueError('revisions must be a list of at most 20 objects.')
    previous = None
    for revision in revisions:
        if not isinstance(revision, dict) or set(revision) != {'timestamp', 'summary'}:
            raise ValueError('Each revision requires timestamp and summary.')
        summary = revision['summary']
        if not isinstance(summary, str) or not summary.strip() or len(summary) > 1000:
            raise ValueError('Invalid revision summary.')
        timestamp = parse_timestamp(revision['timestamp'])
        if previous is not None and timestamp <= previous:
            raise ValueError('Revision timestamps must increase strictly.')
        previous = timestamp
    return data


def analyze_metadata(data):
    validate_metadata(data)
    origin = .95 if data['declared_origin'] == 'ai' else .5
    known_tools = [t for t in data.get('tools', []) if t.strip().lower() in AI_TOOLS]
    generator = data.get('generator', '').strip()
    tools = .95 if known_tools or generator else .5
    count = len(data.get('revisions', []))
    history = .2 if count >= 3 else .35 if count == 2 else .5
    signals = [
        {'name': 'origin_declaration', 'score': origin, 'available': True, 'metrics': {'declared_origin': data['declared_origin']}},
        {'name': 'generation_tools', 'score': tools, 'available': True, 'metrics': {'known_ai_tools': known_tools, 'generator': generator}},
        {'name': 'revision_history', 'score': history, 'available': True, 'metrics': {'revision_count': count, 'independently_verified': False}},
    ]
    weights = [.45, .35, .20]
    index = sum(w*s['score'] for w, s in zip(weights, signals))
    reasons = []
    if max(s['score'] for s in signals)-min(s['score'] for s in signals) > .5:
        reasons.append('signal_disagreement')
        index = max(.31, min(.79, index))
    category = 'uncertain' if reasons else 'likely_ai' if index >= .8 else 'likely_human' if index <= .3 else 'uncertain'
    return {'attribution': category, 'ai_score': round(index, 6), 'confidence': round(max(index, 1-index), 6),
            'confidence_kind': 'heuristic_strength_not_probability', 'label': LABELS[category],
            'uncertainty_reasons': reasons, 'signals': signals, 'signal_weights': weights}
