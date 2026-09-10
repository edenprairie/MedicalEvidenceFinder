"""CLI tests exercise persistence across independent processes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from evidence_demo import ROOT, read


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.memory = Path(self.temporary.name) / "memory.json"
        self.document = Path(self.temporary.name) / "document.json"
        self.fixture = read(ROOT / "fixtures/synthetic.json")
        self.document.write_text(json.dumps(self.fixture))

    def cli(self, *arguments, success=True):
        result = subprocess.run([sys.executable, str(ROOT / "evidence_demo.py"),
                                 "--memory", str(self.memory), "--document", str(self.document),
                                 *arguments], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if success else 2, result.stderr)
        return json.loads(result.stdout) if success else result.stderr

    def remember(self):
        return self.cli("remember", "amber review criteria", "--page", "2", "--quote",
                        "The fictional amber pathway requires a completed sample checklist.",
                        "--author", "test-user", "--reason", "Index is not evidence")

    def test_failure_correction_restart_unrelated_and_revocation(self):
        self.assertEqual(self.cli("search", "amber review criteria")["page"], 1)
        record = self.remember()
        result = self.cli("search", "Amber review criteria!")
        self.assertEqual(result["page"], 2)
        self.assertEqual(result["correction_id"], record["id"])
        destination = result["anchor"]
        self.assertGreater(destination["text_start"], 0)
        self.assertEqual(self.fixture["pages"][1]["text"][destination["text_start"]:destination["text_end"]], result["quote"])
        self.assertIsNone(destination["pdf_destination"])
        self.assertEqual(self.cli("search", "blue review criteria")["page"], 3)
        self.cli("revoke", record["id"])
        self.assertEqual(self.cli("search", "amber review criteria")["page"], 1)
        self.assertFalse(self.cli("list")[0]["active"])

    def test_document_revision_invalidates_memory(self):
        self.remember()
        self.fixture["pages"][1]["text"] += " Updated revision."
        self.document.write_text(json.dumps(self.fixture))
        result = self.cli("search", "amber review criteria")
        self.assertEqual(result["page"], 1)
        self.assertIn("stale", result["diagnostics"][0])

    def test_different_document_does_not_inherit_memory(self):
        self.remember()
        self.fixture["id"] = "different-document"
        self.document.write_text(json.dumps(self.fixture))
        self.assertEqual(self.cli("search", "amber review criteria")["page"], 1)

    def test_invalid_quote_rejected(self):
        error = self.cli("remember", "amber review criteria", "--page", "2", "--quote",
                         "Invented statement", "--author", "test-user", "--reason", "test", success=False)
        self.assertIn("verbatim", error)
        self.assertFalse(self.memory.exists())

    def test_editable_memory_revalidates_evidence(self):
        self.remember()
        records = read(self.memory)
        records[0]["quote"] = "Invented statement"
        self.memory.write_text(json.dumps(records))
        result = self.cli("search", "amber review criteria")
        self.assertEqual(result["page"], 1)
        self.assertIn("invalid evidence", result["diagnostics"][0])

    def test_empty_query_and_malformed_memory_fail_clearly(self):
        self.cli("search", "!!!", success=False)
        self.memory.write_text('[{"active": true}]')
        self.assertIn("Invalid correction", self.cli("search", "amber", success=False))

    def test_no_match_abstains(self):
        self.assertIsNone(self.cli("search", "unfindable")["result"])

    def test_repeated_quote_rejected_as_ambiguous(self):
        self.fixture["pages"][1]["text"] *= 2
        self.document.write_text(json.dumps(self.fixture))
        error = self.cli("remember", "amber", "--page", "2", "--quote", "fictional amber",
                         "--author", "test-user", "--reason", "test", success=False)
        self.assertIn("ambiguous", error)


if __name__ == "__main__":
    unittest.main()
