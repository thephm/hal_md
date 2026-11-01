import io
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "embed_notes.py"


class EmbedNotesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.slugs = ["jane-doe", "john-doe", "pat-smith"]
        for slug in self.slugs:
            (self.folder / slug).mkdir()
        self.people = MagicMock()
        self.people.SECTION_NOTES = "## Notes"
        self.people.get_slugs.return_value = self.slugs
        self.profiles = {}
        for slug in self.slugs:
            profile = MagicMock()
            profile.path = str(self.folder / slug / "Profile.md")
            profile.body.sections = [{"heading": "# Profile", "content": ""}]
            profile.section_top.return_value = "- Manual note"
            self.profiles[slug] = profile
        self.people.read_person_frontmatter.side_effect = (
            lambda slug, folder: self.profiles[slug]
        )
        self.interactions = MagicMock()
        self.modules = {
            name: ModuleType(name)
            for name in ("person", "identity", "md_lookup", "md_frontmatter", "md_body", "md_date")
        }
        self.modules["md_person"] = self.people
        self.modules["md_interactions"] = self.interactions

    def run_script(self, *arguments):
        output = io.StringIO()
        with patch.dict(sys.modules, self.modules), patch.object(
            sys, "argv", [str(SCRIPT), "--folder", str(self.folder), *arguments]
        ), patch.object(sys, "path", sys.path.copy()), redirect_stdout(output), redirect_stderr(output):
            namespace = runpy.run_path(str(SCRIPT), run_name="__main__")
        return namespace, output.getvalue()

    def processed_slugs(self):
        return [call.args[0] for call in self.people.read_person_frontmatter.call_args_list]

    def test_default_processes_all_people(self):
        namespace, _ = self.run_script()
        self.people.get_slugs.assert_called_once_with(str(self.folder))
        self.assertEqual(self.processed_slugs(), self.slugs)
        self.assertEqual(namespace["count"], 3)

    def test_single_slug_skips_enumeration_and_other_profiles(self):
        namespace, _ = self.run_script("--slug", "john-doe")
        self.people.get_slugs.assert_not_called()
        self.assertEqual(self.processed_slugs(), ["john-doe"])
        self.interactions.get_interactions.assert_called_once_with(
            "john-doe", str(self.folder / "john-doe"), []
        )
        self.profiles["john-doe"].update_section.assert_called_once_with(
            "john-doe", "## Notes", "- Manual note\n\n"
        )
        self.profiles["john-doe"].save.assert_called_once()
        self.profiles["jane-doe"].save.assert_not_called()
        self.profiles["pat-smith"].save.assert_not_called()
        self.assertEqual(namespace["count"], 1)

    def test_multiple_and_repeated_slugs_are_deduplicated(self):
        namespace, _ = self.run_script("-s", "john-doe", "jane-doe", "--slug", "john-doe")
        self.people.get_slugs.assert_not_called()
        self.assertEqual(self.processed_slugs(), ["john-doe", "jane-doe"])
        self.assertEqual(namespace["count"], 2)

    def test_max_limits_selected_people(self):
        namespace, _ = self.run_script("--slug", *self.slugs, "--max", "1")
        self.assertEqual(self.processed_slugs(), ["jane-doe"])
        self.assertEqual(namespace["count"], 1)

    def test_missing_slug_is_skipped_without_consuming_max(self):
        namespace, output = self.run_script("--slug", "missing", "john-doe", "--max", "1")
        self.assertIn("could not be found", output)
        self.assertEqual(self.processed_slugs(), ["john-doe"])
        self.assertEqual(namespace["count"], 1)

    def test_invalid_slugs_are_rejected_before_processing(self):
        for slug in ("..", "../outside", "/outside", "C:outside", "nested/person", "nested\\person", "*", "jane-?", "[ab]", ".hidden"):
            with self.subTest(slug=slug), self.assertRaises(SystemExit) as error:
                self.run_script("--slug", slug)
            self.assertEqual(error.exception.code, 2)
        self.people.read_person_frontmatter.assert_not_called()

    def test_slug_requires_a_value(self):
        with self.assertRaises(SystemExit) as error:
            self.run_script("--slug")
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
