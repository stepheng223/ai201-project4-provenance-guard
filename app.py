import json
import os
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
from detection import analyze

load_dotenv()


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(DATABASE_PATH=os.getenv('DATABASE_PATH', 'provenance.sqlite3'), MAX_CONTENT_LENGTH=100_000)
    app.config.update(config or {})
    limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri=app.config.get('RATELIMIT_STORAGE_URI', 'memory://'))

    def connect():
        db = sqlite3.connect(app.config['DATABASE_PATH'], timeout=10)
        db.row_factory = sqlite3.Row
        return db

    with connect() as db:
        db.executescript('CREATE TABLE IF NOT EXISTS content (id TEXT PRIMARY KEY, creator TEXT NOT NULL, data TEXT NOT NULL); CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);')

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
        data = body({'text': 20_000, 'creator_id': 100})
        if data is None:
            return jsonify(error='Provide nonempty text (max 20000) and creator_id (max 100).'), 400
        decision = analyze(data['text'])
        decision.update(content_id=str(uuid4()), creator_id=data['creator_id'], text=data['text'], timestamp=timestamp(), status='classified', appeal_filed=False)
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

    @app.get('/log')
    def log():
        with connect() as db:
            rows = db.execute('SELECT data FROM audit ORDER BY id DESC LIMIT 100').fetchall()
        return jsonify(entries=[json.loads(row['data']) for row in rows])

    @app.get('/health')
    def health():
        return jsonify(status='ok')

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=5000)
