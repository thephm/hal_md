import io
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout

from scan_wikilinks import (
    build_index_frontmatter,
    build_missing_files_body,
    normalize_wikilink_target,
    shorten_progress_message,
    scan_vault,
)


class ScanWikilinksTests(unittest.TestCase):
    def test_normalize_wikilink_target_strips_alias_and_heading(self):
        self.assertEqual(normalize_wikilink_target("notes/Project Plan|Project Plan"), "notes/Project Plan")
        self.assertEqual(normalize_wikilink_target("notes/Project Plan#Heading"), "notes/Project Plan")

    def test_scan_vault_marks_missing_links_and_writes_reports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "notes").mkdir()
            (root / "attachments").mkdir()

            (root / "Alpha.md").write_text("See [[Beta]] and [[Missing Note]] and ![[attachments/photo.jpg]]\n", encoding="utf-8")
            (root / "Beta.md").write_text("Backlink to [[Alpha]]\n", encoding="utf-8")
            (root / "attachments" / "photo.jpg").write_text("fake image", encoding="utf-8")
            (root / "notes" / "Nested.md").write_text("Nested link to [[Alpha]]\n", encoding="utf-8")

            result = scan_vault(root, {".md"}, ".wikilink_index.md", "missing_files.md")

            self.assertEqual(len(result.files), 4)
            self.assertEqual(len(result.folders), 2)
            self.assertEqual(len(result.markdown_files), 3)
            self.assertEqual(len(result.link_records), 5)
            self.assertEqual(len(result.missing_records), 1)
            self.assertEqual(result.missing_records[0].normalized_target, "Missing Note")

            frontmatter = build_index_frontmatter(result)
            missing_body = build_missing_files_body(result)

            self.assertIn("broken_wikilinks: 1", frontmatter)
            self.assertIn("[[Alpha.md]]", missing_body)
            self.assertIn("Missing Note", missing_body)
            self.assertIn("jottacloud.com/web/search/list/name/Missing%20Note", missing_body)

    def test_wikilink_with_extension_resolves_file_in_subfolder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Attachments" / "Indigenous Training").mkdir(parents=True)
            (root / "Attachments" / "Indigenous Training" / "Atris Search.png").write_text("fake", encoding="utf-8")
            (root / "note.md").write_text("![[Atris Search.png]]\n", encoding="utf-8")

            result = scan_vault(root, {".md"}, ".wikilink_index.md", "missing_files.md")

            self.assertEqual(len(result.missing_records), 0, result.missing_records)

    def test_scan_vault_debug_writes_progress_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "nested").mkdir()
            (root / "Alpha.md").write_text("[[Beta]]\n", encoding="utf-8")
            (root / "Beta.md").write_text("[[Alpha]]\n", encoding="utf-8")
            (root / "nested" / "Gamma.md").write_text("[[Alpha]]\n", encoding="utf-8")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = scan_vault(root, {".md"}, ".wikilink_index.md", "missing_files.md", debug=True)

            output = buffer.getvalue()

            self.assertIn("Scanning folder:", output)
            self.assertIn("Scanning file:", output)
            self.assertTrue(output.endswith("\n"))
            self.assertEqual(len(result.link_records), 3)

    def test_scan_vault_max_files_limits_work_done(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "nested").mkdir()
            (root / "Alpha.md").write_text("[[Beta]]\n", encoding="utf-8")
            (root / "Beta.md").write_text("[[Alpha]]\n", encoding="utf-8")
            (root / "nested" / "Gamma.md").write_text("[[Alpha]]\n", encoding="utf-8")

            result = scan_vault(root, {".md"}, ".wikilink_index.md", "missing_files.md", max_files=2)

            self.assertEqual(len(result.files), 2)
            self.assertEqual(len(result.markdown_files), 2)
            self.assertLessEqual(len(result.link_records), 2)

    def test_scan_vault_skips_hidden_vault_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".obsidian").mkdir()
            (root / ".obsidian" / "workspace.json").write_text("{\"foo\": \"bar\"}\n", encoding="utf-8")
            (root / ".hidden.md").write_text("[[Alpha]]\n", encoding="utf-8")
            (root / "Alpha.md").write_text("[[Beta]]\n", encoding="utf-8")
            (root / "Beta.md").write_text("[[Alpha]]\n", encoding="utf-8")

            result = scan_vault(root, {".md"}, ".wikilink_index.md", "missing_files.md", debug=True)

            self.assertNotIn(".obsidian", result.folders)
            self.assertNotIn(".hidden.md", result.files)
            self.assertEqual(len(result.files), 2)
            self.assertEqual(len(result.markdown_files), 2)

    def test_scan_vault_skips_nested_hidden_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "notes").mkdir()
            (root / "notes" / ".cache").mkdir()
            (root / "notes" / ".cache" / "temp.md").write_text("[[Alpha]]\n", encoding="utf-8")
            (root / "notes" / "visible.md").write_text("[[Alpha]]\n", encoding="utf-8")
            (root / "Alpha.md").write_text("[[visible]]\n", encoding="utf-8")

            result = scan_vault(root, {".md"}, ".wikilink_index.md", "missing_files.md")

            self.assertNotIn("notes/.cache", result.folders)
            self.assertNotIn("notes/.cache/temp.md", result.files)
            self.assertEqual(len(result.files), 2)
            self.assertEqual(len(result.markdown_files), 2)

    def test_scan_vault_skips_python_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "notes").mkdir()
            (root / "script.py").write_text("print('hello')\n", encoding="utf-8")
            (root / "notes" / "visible.md").write_text("[[Alpha]]\n", encoding="utf-8")
            (root / "Alpha.md").write_text("[[visible]]\n", encoding="utf-8")

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = scan_vault(root, {".md"}, ".wikilink_index.md", "missing_files.md", debug=True)

            output = buffer.getvalue()

            self.assertNotIn("script.py", output)
            self.assertNotIn("script.py", result.files)
            self.assertEqual(len(result.files), 2)
            self.assertEqual(len(result.markdown_files), 2)

    def test_scan_vault_include_extensions_filters_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Alpha.md").write_text("[[Beta]]", encoding="utf-8")
            (root / "Beta.md").write_text("[[Alpha]]", encoding="utf-8")
            (root / "photo.jpg").write_text("fake", encoding="utf-8")
            (root / "document.pdf").write_text("fake", encoding="utf-8")

            result = scan_vault(
                root, {".md"}, ".wikilink_index.md", "missing_files.md",
                include_extensions={".md"},
            )

            self.assertEqual(len(result.files), 2)
            self.assertNotIn("photo.jpg", result.files)
            self.assertNotIn("document.pdf", result.files)

    def test_scan_vault_skips_output_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "output").mkdir()
            (root / "output" / ".wikilink_index.md").write_text("ignored\n", encoding="utf-8")
            (root / "output" / "missing_files.md").write_text("ignored\n", encoding="utf-8")
            (root / "output" / "note.md").write_text("[[Alpha]]\n", encoding="utf-8")
            (root / "Alpha.md").write_text("[[note]]\n", encoding="utf-8")

            result = scan_vault(root, {".md"}, ".wikilink_index.md", "missing_files.md")

            self.assertNotIn("output", result.folders)
            self.assertNotIn("output/note.md", result.files)
            self.assertNotIn("output/.wikilink_index.md", result.files)
            self.assertNotIn("output/missing_files.md", result.files)
            self.assertEqual(len(result.files), 1)
            self.assertEqual(len(result.markdown_files), 1)

    def test_shorten_progress_message_limits_long_paths(self):
        message = "Scanning file: Attachments/" + "very-long-name-" * 20 + ".pdf"
        shortened = shorten_progress_message(message)

        self.assertLessEqual(len(shortened), 119)
        self.assertTrue(shortened == message or shortened.startswith("..."))


if __name__ == "__main__":
    unittest.main()