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
from production_registry import ProductionSkillRegistry


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

    def test_skill_registry_hot_reloads_markdown_without_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "demo"
            path.mkdir()
            skill = path / "SKILL.md"
            skill.write_text("---\nname: demo\nversion: 1\nstatus: active\n---\nFirst rule")
            registry = SkillRegistry(Path(folder))
            self.assertIn("First rule", registry.active_text())
            skill.write_text("---\nname: demo\nversion: 2\nstatus: active\n---\nUpdated rule")
            self.assertIn("Updated rule", registry.active_text())
            self.assertEqual(registry.list()[0]["version"], "2")

    def test_skill_publish_is_visible_without_restart(self):
        registry = SkillRegistry(Path(__file__).parent / "skills")
        original = Path(__file__).parent.joinpath("skills/evidence-selection/SKILL.md").read_text()
        try:
            updated = original.replace("version: 1.0.1", "version: 1.0.2").replace("Always require human review", "Always require additional human review")
            registry.publish("evidence-selection", updated, "test-user", "Test reviewed skill update")
            self.assertEqual(registry.list()[0]["version"], "1.0.2")
            self.assertIn("additional human review", registry.active_text())
        finally:
            Path(__file__).parent.joinpath("skills/evidence-selection/SKILL.md").write_text(original)

    def test_production_registry_requires_approval_before_activation(self):
        registry = ProductionSkillRegistry(self.data / "production.sqlite")
        draft = registry.submit("evidence-selection", "2.0.0", "---\nstatus: active\n---\nnew", "editor", "new contract")
        with self.assertRaises(ValueError):
            registry.activate("production", draft["id"], "release-bot")
        approved = registry.approve(draft["id"], "reviewer")
        current = registry.activate("production", approved["id"], "release-bot")
        self.assertEqual(current["version"], "2.0.0")
        self.assertEqual(registry.current("production", "evidence-selection")["id"], approved["id"])

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
