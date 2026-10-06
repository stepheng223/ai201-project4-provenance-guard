import json
import hashlib
import secrets
import os
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4
from flask import Flask, jsonify, request, render_template
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from detection import analyze
from metadata_detection import analyze_metadata, parse_timestamp

load_dotenv()


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(DATABASE_PATH=os.getenv('DATABASE_PATH', 'provenance.sqlite3'), MAX_CONTENT_LENGTH=200_000, REVIEWER_TOKEN=os.getenv('REVIEWER_TOKEN', ''))
    app.config.update(config or {})
    limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri=app.config.get('RATELIMIT_STORAGE_URI', 'memory://'))

    def connect():
        db = sqlite3.connect(app.config['DATABASE_PATH'], timeout=10)
        db.row_factory = sqlite3.Row
        return db

    with connect() as db:
        db.executescript('CREATE TABLE IF NOT EXISTS content (id TEXT PRIMARY KEY, creator TEXT NOT NULL, data TEXT NOT NULL); CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL); CREATE TABLE IF NOT EXISTS verification (id TEXT PRIMARY KEY, content_id TEXT UNIQUE NOT NULL, data TEXT NOT NULL);')

    def body(fields):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return None
        for field, maximum in fields.items():
            value = data.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                return None
        return data

    def timestamp():
        return datetime.now(timezone.utc).isoformat()

    @app.errorhandler(429)
    def limited(error):
        return jsonify(error='rate_limit_exceeded', detail=str(error.description)), 429

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error='request_too_large'), 413

    @app.post('/submit')
    @limiter.limit('10 per minute;100 per day')
    def submit():
        data = body({'creator_id': 100})
        if data is None:
            return jsonify(error='Provide nonempty creator_id (max 100).'), 400
        content_type = data.get('content_type', 'text')
        if content_type == 'text':
            if body({'text': 20_000}) is None:
                return jsonify(error='Provide nonempty text (max 20000).'), 400
            decision = analyze(data['text'])
            decision['text'] = data['text']
        elif content_type == 'structured_metadata':
            try:
                decision = analyze_metadata(data.get('metadata'))
            except (ValueError, TypeError) as error:
                return jsonify(error=str(error)), 400
            decision['metadata'] = data['metadata']
        else:
            return jsonify(error='content_type must be text or structured_metadata.'), 400
        decision.update(content_id=str(uuid4()), creator_id=data['creator_id'], content_type=content_type,
                        timestamp=timestamp(), status='classified', appeal_filed=False,
                        certificate=None, certificate_label=None)
        event = dict(decision, event='classification')
        with connect() as db:
            db.execute('INSERT INTO content VALUES (?,?,?)', (decision['content_id'], data['creator_id'], json.dumps(decision)))
            db.execute('INSERT INTO audit(data) VALUES (?)', (json.dumps(event),))
        return jsonify(decision)

    @app.post('/appeal')
    @limiter.limit('10 per minute')
    def appeal():
        data = body({'content_id': 100, 'creator_id': 100, 'creator_reasoning': 4000})
        if data is None:
            return jsonify(error='Provide content_id, creator_id and nonempty creator_reasoning (max 4000).'), 400
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM content WHERE id=?', (data['content_id'],)).fetchone()
            if row is None:
                return jsonify(error='content_not_found'), 404
            if row['creator'] != data['creator_id']:
                return jsonify(error='creator_mismatch'), 403
            current = json.loads(row['data'])
            if current['appeal_filed']:
                return jsonify(error='appeal_already_filed'), 409
            current.update(status='under_review', appeal_filed=True, appeal_reasoning=data['creator_reasoning'], appeal_timestamp=timestamp())
            event = dict(current, event='appeal', original_timestamp=current['timestamp'], timestamp=current['appeal_timestamp'])
            db.execute('UPDATE content SET data=? WHERE id=?', (json.dumps(current), data['content_id']))
            db.execute('INSERT INTO audit(data) VALUES (?)', (json.dumps(event),))
        return jsonify(current)

    @app.get('/content/<content_id>')
    def content(content_id):
        with connect() as db:
            row = db.execute('SELECT data FROM content WHERE id=?', (content_id,)).fetchone()
        return (jsonify(json.loads(row['data'])) if row else (jsonify(error='content_not_found'), 404))

    @app.get('/content/<content_id>/view')
    def content_view(content_id):
        with connect() as db:
            row = db.execute('SELECT data FROM content WHERE id=?', (content_id,)).fetchone()
        if row is None:
            return jsonify(error='content_not_found'), 404
        return render_template('content.html', content=json.loads(row['data']))

    @app.get('/log')
    def log():
        with connect() as db:
            rows = db.execute('SELECT data FROM audit ORDER BY id DESC LIMIT 100').fetchall()
        return jsonify(entries=[json.loads(row['data']) for row in rows])

    def reviewer_error():
        token = app.config['REVIEWER_TOKEN']
        if not token:
            return jsonify(error='reviewer_not_configured'), 503
        supplied = request.headers.get('Authorization', '')
        if not secrets.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
            return jsonify(error='reviewer_authorization_required'), 403
        return None

    @app.post('/verification')
    @limiter.limit('5 per minute')
    def request_verification():
        data = body({'content_id': 100, 'creator_id': 100, 'creator_reasoning': 4000})
        if data is None:
            return jsonify(error='Provide content_id, creator_id and creator_reasoning.'), 400
        drafts = data.get('drafts')
        if not isinstance(drafts, list) or not 2 <= len(drafts) <= 5:
            return jsonify(error='Provide between two and five drafts.'), 400
        previous = None
        texts = []
        try:
            for draft in drafts:
                if not isinstance(draft, dict) or set(draft) != {'text', 'timestamp'}:
                    raise ValueError('Each draft requires text and timestamp.')
                text = draft['text']
                if not isinstance(text, str) or not text.strip() or len(text) > 20000:
                    raise ValueError('Each draft must be nonempty and at most 20000 characters.')
                date = parse_timestamp(draft['timestamp'])
                if previous is not None and date <= previous:
                    raise ValueError('Draft timestamps must increase strictly.')
                texts.append(text)
                previous = date
            if len(set(texts)) < 2:
                raise ValueError('At least two distinct draft versions are required.')
        except (ValueError, TypeError) as error:
            return jsonify(error=str(error)), 400
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM content WHERE id=?', (data['content_id'],)).fetchone()
            if row is None:
                return jsonify(error='content_not_found'), 404
            if row['creator'] != data['creator_id']:
                return jsonify(error='creator_mismatch'), 403
            current = json.loads(row['data'])
            if current.get('content_type', 'text') != 'text':
                return jsonify(error='Draft verification is available for text content only.'), 400
            if texts[-1] != current['text'] or previous > parse_timestamp(current['timestamp']):
                return jsonify(error='Final draft must match submitted text and precede submission.'), 400
            if db.execute('SELECT id FROM verification WHERE content_id=?', (data['content_id'],)).fetchone():
                return jsonify(error='verification_already_requested'), 409
            record = dict(verification_id=str(uuid4()), content_id=data['content_id'], creator_id=data['creator_id'],
                          creator_reasoning=data['creator_reasoning'], drafts=drafts, status='pending', timestamp=timestamp())
            db.execute('INSERT INTO verification VALUES (?,?,?)', (record['verification_id'], data['content_id'], json.dumps(record)))
            event = dict(current, event='verification_requested', timestamp=record['timestamp'], verification_id=record['verification_id'])
            db.execute('INSERT INTO audit(data) VALUES (?)', (json.dumps(event),))
        return jsonify(record), 201

    @app.get('/verification/<verification_id>')
    def inspect_verification(verification_id):
        error = reviewer_error()
        if error is not None:
            return error
        with connect() as db:
            row = db.execute('SELECT data FROM verification WHERE id=?', (verification_id,)).fetchone()
        return jsonify(json.loads(row['data'])) if row else (jsonify(error='verification_not_found'), 404)

    @app.post('/verification/<verification_id>/review')
    @limiter.limit('10 per minute')
    def review_verification(verification_id):
        error = reviewer_error()
        if error is not None:
            return error
        data = body({'review_notes': 4000})
        if data is None or not isinstance(data.get('approved'), bool):
            return jsonify(error='Provide approved (boolean) and nonempty review_notes.'), 400
        with connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM verification WHERE id=?', (verification_id,)).fetchone()
            if row is None:
                return jsonify(error='verification_not_found'), 404
            record = json.loads(row['data'])
            if record['status'] != 'pending':
                return jsonify(error='verification_already_reviewed'), 409
            current = json.loads(db.execute('SELECT data FROM content WHERE id=?', (record['content_id'],)).fetchone()['data'])
            now = timestamp()
            record.update(status='approved' if data['approved'] else 'rejected', review_notes=data['review_notes'], reviewed_at=now)
            if data['approved']:
                current['certificate'] = {'certificate_id': str(uuid4()), 'content_id': current['content_id'],
                    'creator_id': current['creator_id'], 'verification_id': verification_id, 'issued_at': now,
                    'text_sha256': hashlib.sha256(current['text'].encode()).hexdigest(),
                    'verification_method': 'human_review_of_draft_history'}
                current['certificate_label'] = 'Verified human — draft history reviewed'
            db.execute('UPDATE verification SET data=? WHERE id=?', (json.dumps(record), verification_id))
            db.execute('UPDATE content SET data=? WHERE id=?', (json.dumps(current), record['content_id']))
            event = dict(current, event='verification_approved' if data['approved'] else 'verification_rejected',
                         timestamp=now, verification_id=verification_id, review_notes=data['review_notes'])
            db.execute('INSERT INTO audit(data) VALUES (?)', (json.dumps(event),))
        return jsonify(verification=record, content=current)

    def analytics_data():
        with connect() as db:
            records = [json.loads(row['data']) for row in db.execute('SELECT data FROM content')]
        total = len(records)
        counts = {category: sum(r['attribution'] == category for r in records)
                  for category in ('likely_ai', 'likely_human', 'uncertain')}
        appeals = sum(bool(r.get('appeal_filed')) for r in records)
        return {'total_submissions': total, 'attribution_counts': counts,
                'attribution_ratios': {key: value/total if total else 0 for key, value in counts.items()},
                'appealed_submissions': appeals, 'appeal_rate': appeals/total if total else 0,
                'mean_confidence': sum(r['confidence'] for r in records)/total if total else 0,
                'verified_submissions': sum(bool(r.get('certificate')) for r in records),
                'content_type_counts': {kind: sum(r.get('content_type', 'text') == kind for r in records)
                                       for kind in ('text', 'structured_metadata')}}

    @app.get('/analytics')
    def analytics():
        return jsonify(analytics_data())

    @app.get('/dashboard')
    def dashboard():
        return render_template('dashboard.html', metrics=analytics_data())

    @app.get('/health')
    def health():
        return jsonify(status='ok')

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5000)
