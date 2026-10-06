import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from app import create_app
from detection import analyze, combine, discourse, LABELS

FIXTURES = {
    'uniform_synthetic': 'Furthermore, stakeholders in modern society recognize a transformative paradigm in responsible deployment. Furthermore, it is important to note that stakeholders consider deployment equally essential. In conclusion, stakeholders in modern society consider responsible deployment a transformative paradigm. Furthermore, it is important to note that responsible deployment remains equally essential.',
    'ai_style': 'Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment.',
    'human_style': "ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after. my friend got the spicy version and said it was better. probably won't go back unless someone drags me there",
    'formal_human_borderline': 'The relationship between monetary policy and asset price inflation has been extensively studied in the literature. Central banks face a fundamental tension between their mandate for price stability and the unintended consequences of prolonged low interest rates on equity and real estate valuations.',
    'edited_ai_borderline': "I've been thinking a lot about remote work lately. There are genuine tradeoffs — flexibility and no commute on one side, isolation and blurred work-life boundaries on the other. Studies show productivity varies widely by individual and role type.",
}


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = {'TESTING': True, 'DATABASE_PATH': self.tmp.name + '/test.sqlite3'}
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.env = patch.dict(os.environ, {'DETECTION_MODE': 'offline'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def submit(self, text=None):
        return self.client.post('/submit', json={'text': text or FIXTURES['ai_style'], 'creator_id': 'demo'})

    def test_examples_and_labels(self):
        results = {key: self.submit(text).get_json() for key, text in FIXTURES.items()}
        self.assertEqual(results['ai_style']['attribution'], 'uncertain')
        self.assertEqual(results['uniform_synthetic']['attribution'], 'likely_ai')
        self.assertEqual(results['human_style']['attribution'], 'likely_human')
        self.assertEqual(results['formal_human_borderline']['attribution'], 'uncertain')
        self.assertEqual(results['edited_ai_borderline']['attribution'], 'uncertain')
        for result in results.values():
            self.assertEqual(result['label'], LABELS[result['attribution']])
        self.assertGreater(results['ai_style']['ai_score']-results['human_style']['ai_score'], .5)

    def test_validation_and_short_text(self):
        for payload in [None, {}, [], {'text': 3, 'creator_id': 'x'}, {'text': ' ', 'creator_id': 'x'}, {'text': 'x'*20001, 'creator_id': 'x'}]:
            self.assertEqual(self.client.post('/submit', json=payload).status_code, 400)
        self.assertEqual(self.submit('Hello there.').get_json()['attribution'], 'uncertain')

    def test_appeal_and_persistence(self):
        original = self.submit().get_json()
        payload = {'content_id': original['content_id'], 'creator_id': 'wrong', 'creator_reasoning': 'I wrote this.'}
        self.assertEqual(self.client.post('/appeal', json=payload).status_code, 403)
        payload['creator_id'] = 'demo'
        accepted = self.client.post('/appeal', json=payload)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.get_json()['status'], 'under_review')
        self.assertEqual(self.client.post('/appeal', json=payload).status_code, 409)
        payload['content_id'] = 'missing'
        self.assertEqual(self.client.post('/appeal', json=payload).status_code, 404)
        other_client = create_app(self.config).test_client()
        self.assertEqual(other_client.get('/content/'+original['content_id']).get_json()['status'], 'under_review')
        events = other_client.get('/log').get_json()['entries']
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]['status'], 'classified')
        self.assertEqual(events[0]['appeal_reasoning'], 'I wrote this.')
        self.assertEqual(events[0]['attribution'], original['attribution'])

    def test_rate_limit(self):
        codes = [self.submit('Testing the limit.').status_code for _ in range(12)]
        self.assertEqual(codes, [200]*10+[429]*2)

    def test_thresholds_disagreement_and_failure(self):
        second = {'score': .8, 'metrics': {'word_count': 40}}
        self.assertEqual(combine({'score': .8, 'available': True}, second)['attribution'], 'likely_ai')
        second['score'] = .3
        self.assertEqual(combine({'score': .3, 'available': True}, second)['attribution'], 'likely_human')
        second['score'] = .1
        self.assertEqual(combine({'score': .95, 'available': True}, second)['attribution'], 'uncertain')
        with patch.dict(os.environ, {'DETECTION_MODE': 'groq', 'GROQ_API_KEY': '', 'GROQ_MODEL': ''}):
            result = analyze(FIXTURES['ai_style'])
        self.assertIn('provider_unavailable', result['uncertainty_reasons'])
        self.assertEqual(result['attribution'], 'uncertain')

    def test_invalid_provider_scores(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps({'choices': [{'message': {'content': '{"ai_score": true}'}}]}).encode()
        with patch.dict(os.environ, {'DETECTION_MODE': 'groq', 'GROQ_API_KEY': 'test', 'GROQ_MODEL': 'test'}), patch('urllib.request.urlopen', return_value=Response()):
            self.assertFalse(discourse('test')['available'])

    def test_provider_explanation_contract(self):
        class Response:
            def __init__(self, result): self.result = result
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({'choices': [{'message': {'content': json.dumps(self.result)}}]}).encode()
        with patch.dict(os.environ, {'DETECTION_MODE': 'groq', 'GROQ_API_KEY': 'test', 'GROQ_MODEL': 'test'}):
            for explanation in (None, '', ' ', {'reason': 'uniform'}):
                with patch('urllib.request.urlopen', return_value=Response({'ai_score': .9, 'explanation': explanation})):
                    self.assertFalse(discourse('test')['available'])
            with patch('urllib.request.urlopen', return_value=Response({'ai_score': .9, 'explanation': 'Uniform discourse.'})):
                result = discourse('test')
                self.assertTrue(result['available'])
                self.assertEqual(result['score'], .9)


def evidence():
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DETECTION_MODE': 'offline'}):
        client = create_app({'TESTING': True, 'DATABASE_PATH': folder+'/evidence.sqlite3'}).test_client()
        results = {key: client.post('/submit', json={'text': text, 'creator_id': 'demo'}).get_json() for key, text in FIXTURES.items()}
        client.post('/appeal', json={'content_id': results['formal_human_borderline']['content_id'], 'creator_id': 'demo', 'creator_reasoning': 'I wrote this academic passage myself; formal language does not establish AI authorship.'})
        Path('evidence/examples.json').write_text(json.dumps(results, indent=2)+'\n')
        Path('evidence/audit-sample.json').write_text(json.dumps(client.get('/log').get_json(), indent=2)+'\n')
        fresh = create_app({'TESTING': True, 'DATABASE_PATH': folder+'/limit.sqlite3'}).test_client()
        codes = [fresh.post('/submit', json={'text': 'Rate limit evidence.', 'creator_id': 'demo'}).status_code for _ in range(12)]
        Path('evidence/rate-limit.txt').write_text('\n'.join(map(str, codes))+'\n')
        print(json.dumps({key: {field: value[field] for field in ('ai_score', 'confidence', 'attribution')} for key, value in results.items()}, indent=2))


if __name__ == '__main__':
    import sys
    if '--evidence' in sys.argv:
        evidence()
    else:
        unittest.main()
