import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import HTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from prototype import Prototype, handler
from skill_registry import SkillRegistry


class PrototypeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.app = Prototype(self.data)

    def teach(self, text):
        preview = self.app.action('/api/preview', dict(text=text))
        return self.app.action('/api/save', dict(preview, author='Presenter'))

    def search(self, query):
        return self.app.action('/api/search', dict(query=query))

    def test_teach_edit_persist_revoke_and_reset(self):
        self.assertEqual(self.search('amber review criteria')['result']['page'], 1)
        record = self.teach('Remember: use page 2 for "amber review criteria" quote "The fictional amber pathway requires a completed sample checklist."')
        self.app = Prototype(self.data)
        self.assertEqual(self.search('amber review criteria')['result']['page'], 2)
        edited = self.app.action('/api/save', dict(record, kind='correction', reason='Updated explanation'))
        self.assertNotEqual(edited['id'], record['id'])
        self.assertFalse(self.app.state()['corrections'][0]['active'])
        self.assertEqual(self.search('blue review criteria')['result']['page'], 3)
        self.app.action('/api/revoke', dict(kind='correction', id=edited['id']))
        self.assertEqual(self.search('amber review criteria')['result']['page'], 1)
        with self.assertRaises(ValueError):
            self.app.action('/api/reset', {})
        self.app.action('/api/reset', dict(confirmation='RESET DEMO'))
        self.assertEqual(self.app.state()['corrections'], [])

    def test_vocabulary_notes_and_isolation(self):
        record = self.teach('Remember: "amber eligibility" means "amber review criteria"')
        self.teach('Note "amber eligibility": Reviewed user knowledge, not evidence.')
        self.app = Prototype(self.data)
        response = self.search('amber eligibility')
        self.assertEqual(response['resolved_query'], 'amber review criteria')
        self.assertEqual(len(response['notes']), 1)
        self.assertEqual(self.search('blue review criteria')['vocabulary_ids'], [])
        self.app.document['id'] = 'another-document'
        self.assertEqual(self.search('amber eligibility')['vocabulary_ids'], [])
        self.assertEqual(self.search('amber eligibility')['notes'], [])
        self.app = Prototype(self.data)
        self.app.action('/api/revoke', dict(kind='vocabulary', id=record['id']))
        self.assertEqual(self.search('amber eligibility')['vocabulary_ids'], [])

    def test_parser_and_invalid_quote_save_nothing(self):
        for text in ['Understand everything from now on', 'Remember: use page 2 for "amber" quote "invented"']:
            with self.assertRaises(ValueError):
                self.teach(text)
        self.assertEqual(self.app.state()['corrections'], [])

    def test_skill_registry_lists_active_skill_and_builds_prompt_context(self):
        registry = SkillRegistry(Path(__file__).parent / "skills")
        self.assertEqual(registry.list()[0]["name"], "evidence-selection")
        context = registry.build_prompt_context("amber", "synthetic-family", {"active": 1})
        self.assertIn("Never transfer a page number alone", context)
        self.assertIn("query=amber", context)

    def test_http_search_and_origin_protection(self):
        server = HTTPServer(('127.0.0.1', 0), handler(self.app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}'
            self.assertIn(b'Source reader', urlopen(url).read())
            request = Request(url+'/api/search', data=json.dumps(dict(query='amber review criteria')).encode(), headers={'Content-Type':'application/json'})
            self.assertEqual(json.load(urlopen(request))['result']['page'], 1)
            request.add_header('Origin', 'https://example.com')
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
