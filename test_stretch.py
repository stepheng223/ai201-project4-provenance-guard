import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import create_app
from detection import analyze, reference_match, combine
from test_app import FIXTURES

METADATA = {
    'asset_name': 'Sunset cover illustration', 'media_type': 'image', 'declared_origin': 'ai',
    'tools': ['DALL-E 3'], 'generator': 'DALL-E 3', 'revisions': [],
}
DRAFT_TIMES = ['2026-01-01T10:00:00Z', '2026-01-01T11:00:00Z']


class StretchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {'TESTING': True, 'DATABASE_PATH': self.tmp.name+'/test.sqlite3', 'REVIEWER_TOKEN': 'test-reviewer'}
        self.client = create_app(self.config).test_client()
        self.env = patch.dict(os.environ, {'DETECTION_MODE': 'offline'})
        self.env.start()
        self.headers = {'Authorization': 'Bearer test-reviewer'}

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def submit(self):
        return self.client.post('/submit', json={'creator_id': 'writer', 'text': FIXTURES['human_style']}).get_json()

    def verification_payload(self, content):
        return {'content_id': content['content_id'], 'creator_id': 'writer', 'creator_reasoning': 'I retained drafts of my own account.',
                'drafts': [{'text': 'The ramen was too salty. This is my first draft.', 'timestamp': DRAFT_TIMES[0]},
                           {'text': content['text'], 'timestamp': DRAFT_TIMES[1]}]}

    def test_three_distinct_signals_and_reference_match(self):
        result = analyze(FIXTURES['uniform_synthetic'])
        self.assertEqual([s['name'] for s in result['signals']], ['lexical_discourse', 'stylometry', 'reference_match'])
        self.assertEqual(result['signal_weights'], [.55, .30, .15])
        self.assertEqual(result['signals'][2]['score'], .95)
        self.assertEqual(reference_match('Unrelated zebras jump through moonlit rivers')['score'], .5)
        first = {'score': .95, 'available': True}
        second = {'score': .85, 'metrics': {'word_count': 40}}
        third = {'score': .3}
        result = combine(first, second, third)
        self.assertEqual(result['attribution'], 'uncertain')
        self.assertIn('signal_disagreement', result['uncertainty_reasons'])

    def test_certificate_requires_review_and_persists(self):
        content = self.submit()
        request = self.client.post('/verification', json=self.verification_payload(content))
        self.assertEqual(request.status_code, 201)
        verification = request.get_json()
        url = '/verification/'+verification['verification_id']
        self.assertIsNone(self.client.get('/content/'+content['content_id']).get_json()['certificate'])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(url, headers=self.headers).get_json()['drafts'][-1]['text'], content['text'])
        approval = {'approved': True, 'review_notes': 'Reviewed distinct draft versions and creator explanation.'}
        self.assertEqual(self.client.post(url+'/review', json=approval).status_code, 403)
        self.assertEqual(self.client.post(url+'/review', headers=self.headers, json=dict(approval, approved='true')).status_code, 400)
        response = self.client.post(url+'/review', headers=self.headers, json=approval)
        self.assertEqual(response.status_code, 200)
        approved = response.get_json()['content']
        self.assertEqual(approved['certificate']['text_sha256'], hashlib.sha256(content['text'].encode()).hexdigest())
        self.assertEqual(approved['certificate_label'], 'Verified human — draft history reviewed')
        self.assertEqual(approved['label'], content['label'])
        self.assertEqual(approved['attribution'], content['attribution'])
        self.assertEqual(self.client.post(url+'/review', headers=self.headers, json=approval).status_code, 409)
        other = create_app(self.config).test_client()
        self.assertEqual(other.get('/content/'+content['content_id']).get_json()['certificate'], approved['certificate'])
        events = other.get('/log').get_json()['entries']
        self.assertEqual([e['event'] for e in events], ['verification_approved', 'verification_requested', 'classification'])
        html = other.get('/content/'+content['content_id']+'/view').get_data(as_text=True)
        self.assertIn('Verified human', html)
        self.assertIn(content['label'], html)

    def test_invalid_verification_evidence(self):
        content = self.submit()
        payload = self.verification_payload(content)
        cases = [dict(payload, creator_id='other'), dict(payload, content_id='missing'),
                 dict(payload, drafts=[payload['drafts'][0]]),
                 dict(payload, drafts=[payload['drafts'][0], dict(payload['drafts'][1], text='Wrong final text')]),
                 dict(payload, drafts=[dict(payload['drafts'][0], timestamp='bad'), payload['drafts'][1]]),
                 dict(payload, drafts=[dict(payload['drafts'][0], timestamp='2026-01-01T12:00:00Z'), payload['drafts'][1]]),
                 dict(payload, drafts=[dict(payload['drafts'][0], timestamp='2099-01-01T10:00:00Z'), payload['drafts'][1]])]
        for number, (value, expected) in enumerate(zip(cases, [403,404,400,400,400,400,400])):
            self.assertEqual(self.client.post('/verification', json=value, environ_overrides={'REMOTE_ADDR': '127.0.1.'+str(number+1)}).status_code, expected)
        self.assertEqual(self.client.post('/verification', json=payload).status_code, 201)
        self.assertEqual(self.client.post('/verification', json=payload).status_code, 409)

    def test_rejection_and_unconfigured_reviewer(self):
        content = self.submit()
        record = self.client.post('/verification', json=self.verification_payload(content)).get_json()
        url = '/verification/'+record['verification_id']+'/review'
        disabled = create_app(dict(self.config, REVIEWER_TOKEN='')).test_client()
        self.assertEqual(disabled.post(url, json={'approved': True, 'review_notes': 'test'}, headers=self.headers).status_code, 503)
        response = self.client.post(url, json={'approved': False, 'review_notes': 'Draft history is not persuasive.'}, headers=self.headers)
        self.assertEqual(response.get_json()['verification']['status'], 'rejected')
        self.assertIsNone(response.get_json()['content']['certificate'])
        self.assertEqual(self.client.get('/log').get_json()['entries'][0]['event'], 'verification_rejected')

    def test_metadata_classification_and_appeal(self):
        response = self.client.post('/submit', json={'creator_id': 'artist', 'content_type': 'structured_metadata', 'metadata': METADATA})
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result['attribution'], 'likely_ai')
        self.assertAlmostEqual(result['ai_score'], .86)
        self.assertEqual(len(result['signals']), 3)
        self.assertEqual(result['metadata'], METADATA)
        self.assertNotIn('text', result)
        self.assertIn('metadata', result['label'])
        response = self.client.post('/appeal', json={'creator_id': 'artist', 'content_id': result['content_id'], 'creator_reasoning': 'The export recorded the wrong tool.'})
        self.assertEqual(response.get_json()['status'], 'under_review')
        self.assertEqual(self.client.get('/log').get_json()['entries'][0]['metadata'], METADATA)
        payload = {'content_id': result['content_id'], 'creator_id': 'artist', 'creator_reasoning': 'Verify asset',
                   'drafts': [{'text': 'one', 'timestamp': DRAFT_TIMES[0]}, {'text': 'two', 'timestamp': DRAFT_TIMES[1]}]}
        self.assertEqual(self.client.post('/verification', json=payload).status_code, 400)

    def test_metadata_validation_and_conflicts(self):
        invalid = [None, [], dict(METADATA, media_type='document'), dict(METADATA, tools='DALL-E'),
                   dict(METADATA, declared_origin=True), dict(METADATA, generator={}), dict(METADATA, unknown='x'),
                   dict(METADATA, revisions=[{'timestamp': 'not-a-date', 'summary': 'draft'}]),
                   dict(METADATA, revisions=[{'timestamp': '2026-01-01', 'summary': 'draft'}])]
        for metadata in invalid:
            self.assertEqual(self.client.post('/submit', json={'creator_id': 'artist', 'content_type': 'structured_metadata', 'metadata': metadata}).status_code, 400)
        revisions = [{'timestamp': '2026-01-0'+str(i)+'T10:00:00Z', 'summary': 'Revision '+str(i)} for i in range(1,4)]
        result = self.client.post('/submit', json={'creator_id': 'artist', 'content_type': 'structured_metadata', 'metadata': dict(METADATA, revisions=revisions)}, environ_overrides={'REMOTE_ADDR': '127.0.0.2'}).get_json()
        self.assertEqual(result['attribution'], 'uncertain')
        self.assertIn('signal_disagreement', result['uncertainty_reasons'])

    def test_analytics_counts_content_once_and_empty_dashboard(self):
        empty = self.client.get('/analytics').get_json()
        self.assertEqual(empty['total_submissions'], 0)
        self.assertEqual(empty['appeal_rate'], 0)
        self.assertEqual(empty['mean_confidence'], 0)
        self.assertIn('No submissions yet', self.client.get('/dashboard').get_data(as_text=True))
        text = self.submit()
        metadata = self.client.post('/submit', json={'creator_id': 'artist', 'content_type': 'structured_metadata', 'metadata': METADATA}).get_json()
        self.client.post('/appeal', json={'creator_id': 'writer', 'content_id': text['content_id'], 'creator_reasoning': 'I wrote this.'})
        record = self.client.post('/verification', json=self.verification_payload(text)).get_json()
        self.client.post('/verification/'+record['verification_id']+'/review', json={'approved': True, 'review_notes': 'Reviewed.'}, headers=self.headers)
        metrics = self.client.get('/analytics').get_json()
        self.assertEqual(metrics['total_submissions'], 2)
        self.assertEqual(metrics['appeal_rate'], .5)
        self.assertEqual(metrics['verified_submissions'], 1)
        self.assertEqual(metrics['attribution_counts'], {'likely_ai': 1, 'likely_human': 1, 'uncertain': 0})
        self.assertAlmostEqual(metrics['mean_confidence'], (text['confidence']+metadata['confidence'])/2)
        html = self.client.get('/dashboard').get_data(as_text=True)
        for label in ('Detection patterns', 'Appeal rate', 'Mean confidence strength', '50.0%', 'Verified human credentials'):
            self.assertIn(label, html)


def evidence():
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DETECTION_MODE': 'offline'}):
        config = {'TESTING': True, 'DATABASE_PATH': folder+'/stretch.sqlite3', 'REVIEWER_TOKEN': 'ephemeral-demo-token'}
        client = create_app(config).test_client()
        headers = {'Authorization': 'Bearer ephemeral-demo-token'}
        ensemble = client.post('/submit', json={'creator_id': 'synthetic-demo', 'text': FIXTURES['uniform_synthetic']}).get_json()
        human = client.post('/submit', json={'creator_id': 'writer-demo', 'text': FIXTURES['human_style']}).get_json()
        metadata = client.post('/submit', json={'creator_id': 'artist-demo', 'content_type': 'structured_metadata', 'metadata': METADATA}).get_json()
        client.post('/appeal', json={'content_id': metadata['content_id'], 'creator_id': 'artist-demo', 'creator_reasoning': 'Please review this asset metadata.'})
        request = {'content_id': human['content_id'], 'creator_id': 'writer-demo', 'creator_reasoning': 'Here are drafts of my account.',
                   'drafts': [{'text': 'First draft: the broth was too salty.', 'timestamp': DRAFT_TIMES[0]}, {'text': human['text'], 'timestamp': DRAFT_TIMES[1]}]}
        pending = client.post('/verification', json=request).get_json()
        reviewed = client.post('/verification/'+pending['verification_id']+'/review', headers=headers,
                               json={'approved': True, 'review_notes': 'Demo reviewer examined drafts and attested human authorship; not independent proof.'}).get_json()
        Path('evidence/stretch.json').write_text(json.dumps({'ensemble': ensemble, 'structured_metadata': metadata,
            'verification_request': request, 'pending_verification': pending, 'review_result': reviewed,
            'analytics': client.get('/analytics').get_json(), 'audit': client.get('/log').get_json()}, indent=2)+'\n')
        Path('evidence/dashboard.html').write_text(client.get('/dashboard').get_data(as_text=True))
        Path('evidence/verified-content.html').write_text(client.get('/content/'+human['content_id']+'/view').get_data(as_text=True))
        print('Generated stretch evidence, dashboard HTML and verified-content HTML.')


if __name__ == '__main__':
    import sys
    if '--evidence' in sys.argv: evidence()
    else: unittest.main()
