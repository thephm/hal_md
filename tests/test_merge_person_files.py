import datetime as dt
import csv
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

from tools.bio_summary import BioSummaryError
from tools.markdown_cleanup import normalize_heading_spacing

from tools.merge_person_files import (
    FRONTMATTER_FIELD_ORDER, PersonSynchronizer, SyncStore, build_parser,
    default_config_dir, default_dev_output_dir,
    dates_overlap, discover_people, main, normalize_city, normalize_position_description, read_document, render_position_blocks, review_context, review_pending, section_content, source_hash,
)
from text_encoding import repair_mojibake


class SyncPersonFilesTests(unittest.TestCase):
    def test_final_merge_normalizes_every_heading_and_empty_sections(self):
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n# Jane Doe\n\n\n"
            "## Positions\n\n\n- \n\n## Notes\n\n\n### Detail\nText\n",
        )
        other_path = self.write_person(
            self.other_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n",
        )
        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.merge_pair(read_document(person_path), read_document(other_path))
        updated = person_path.read_text(encoding="utf-8")
        self.assertEqual(updated, normalize_heading_spacing(updated))
        self.assertIn("# Jane Doe\n\n## Positions\n\n## Notes\n\n### Detail\n\nText\n", updated)
        synchronizer.merge_pair(read_document(person_path), read_document(other_path))
        self.assertEqual(person_path.read_text(encoding="utf-8"), updated)

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)
        self.personal_root = self.root / "personal"
        self.other_root = self.root / "other"
        self.state_root = self.root / "state"
        self.personal_root.mkdir()
        self.other_root.mkdir()

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_default_registry_paths_support_windows_and_wsl(self):
        self.assertEqual(default_dev_output_dir("nt", {}), Path(r"C:\data\dev-output"))
        self.assertEqual(default_dev_output_dir("posix", {}), Path("/mnt/c/data/dev-output"))
        self.assertEqual(default_config_dir("nt", {}), Path(r"C:\data\config"))
        self.assertEqual(default_config_dir("posix", {}), Path("/mnt/c/data/config"))
        self.assertEqual(default_config_dir("posix", {"HAL_MD_CONFIG_DIR": "/data/config"}), Path("/data/config"))
        self.assertEqual(default_config_dir("nt", {"HAL_MD_DEV_OUTPUT_DIR": r"D:\output"}), Path(r"C:\data\config"))

    def test_normalize_city_removes_metropolitan_suffixes(self):
        self.assertEqual(normalize_city("Ottawa Metropolitan"), "Ottawa")
        self.assertEqual(normalize_city("Toronto Metropolitan Area"), "Toronto")
        self.assertEqual(normalize_city("Fort Lauderdale"), "Fort Lauderdale")

    def test_frontmatter_none_placeholders_are_removed_without_touching_body(self):
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nskills:\n  - None\n  - Python\n"
            "interests: [None]\nlabel: \"None\"\nprivate_field: keep exactly\n"
            "metadata: {label: 'None', keep: None of these}\n---\n## Notes\n\n- None\n",
        )
        other_path = self.write_person(
            self.other_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nskills: [None, Rust]\nmobile: None\n---\n",
        )
        original_incoming = other_path.read_bytes()
        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.merge_pair(read_document(person_path), read_document(other_path))
        person = read_document(person_path)
        self.assertEqual(person.frontmatter["skills"], ["Python", "Rust"])
        self.assertEqual(person.frontmatter["interests"] or [], [])
        self.assertFalse(person.frontmatter["label"])
        self.assertEqual(person.frontmatter["metadata"], {"label": "", "keep": "None of these"})
        self.assertNotIn("mobile: None", person.raw)
        self.assertIn("private_field: keep exactly\n", person.raw)
        self.assertTrue(person.raw.endswith("## Notes\n\n- None\n"))
        self.assertEqual(other_path.read_bytes(), original_incoming)
        synchronizer.merge_pair(person, read_document(other_path))
        self.assertEqual(person_path.read_text(encoding="utf-8"), person.raw)

    def test_frontmatter_none_cleanup_during_normalization_and_creation(self):
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nlabel: None\n---\n## Notes\n\nNone\n",
        )
        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.normalize_markdown_in_people([read_document(person_path)])
        self.assertFalse(read_document(person_path).frontmatter["label"])
        other_path = self.write_person(
            self.other_root, "john-doe",
            "---\ntags: [person]\nslug: john-doe\nfirst_name: John\nlast_name: Doe\n"
            "organizations: [None, acme]\nlabel: None\n---\n",
        )
        synchronizer.create_person(read_document(other_path), set())
        created = read_document(self.personal_root / "john-doe" / "John Doe.md")
        self.assertEqual(created.frontmatter["organizations"], ["acme"])
        self.assertFalse(created.frontmatter["label"])

    def test_config_directory_selects_organization_registry(self):
        config_dir = self.root / "config"
        config_dir.mkdir()
        with patch("tools.merge_person_files.load_organization_aliases", return_value={}) as loader:
            self.assertEqual(main([
                "-e", str(self.personal_root), "-t", str(self.state_root),
                "--config", str(config_dir), "-m", "-n",
            ]), 0)
        loader.assert_called_once_with(config_dir / "organizations.json")

    def test_explicit_organization_registry_overrides_config_directory(self):
        registry_path = self.root / "custom-organizations.json"
        with patch("tools.merge_person_files.load_organization_aliases", return_value={}) as loader:
            self.assertEqual(main([
                "-e", str(self.personal_root), "-t", str(self.state_root),
                "--config", str(self.root), "--organizations-config", str(registry_path),
                "-m", "-n",
            ]), 0)
        loader.assert_called_once_with(registry_path)

    def test_config_json_still_loads_sync_settings(self):
        config_path = self.root / "sync-settings.json"
        config_path.write_text('{"bio_similarity": 0.85}', encoding="utf-8")
        with patch(
            "tools.merge_person_files.PersonSynchronizer.normalize_positions", autospec=True,
        ) as normalize:
            self.assertEqual(main([
                "-e", str(self.personal_root), "-t", str(self.state_root),
                "--config", str(config_path), "-m", "-n",
            ]), 0)
        self.assertEqual(normalize.call_args.args[0].args.bio_similarity, 0.85)

    def test_repair_mojibake_is_available_as_shared_utility(self):
        self.assertEqual(repair_mojibake("SecrÃ©tariat"), "Secrétariat")
        self.assertEqual(repair_mojibake("Laurentienne Générale"), "Laurentienne Générale")

    def test_general_do_not_summarize_flag_is_default_enabled_with_opt_out(self):
        self.assertTrue(build_parser().parse_args([]).summarize_bio)
        self.assertFalse(build_parser().parse_args(["--do-not-summarize"]).summarize_bio)

    def test_bio_summary_uses_both_sources_and_is_reused_across_runs(self):
        personal_bio = "Managed worldwide technology projects and budgets of up to $30 million. " * 6
        incoming_bio = "Senior project manager delivering cloud and analytics projects. " * 6
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            f"---\ntags: [person]\nslug: jane-doe\n---\n## Bio\n\n> {personal_bio}\n\n## Notes\n\nKeep notes.\n",
        )
        other_path = self.write_person(
            self.other_root, "jane-doe",
            f"---\ntags: [person]\nslug: jane-doe\n---\n## Bio\n\n{incoming_bio}\n",
        )
        summary = "Senior project manager delivering technology, cloud and analytics projects with budgets up to $30 million."
        args = self.arguments()
        args.summarize_bio = True
        fake = Mock()
        fake.summarize.return_value = summary
        with patch("tools.merge_person_files.BioSummarizer.from_settings", return_value=fake):
            synchronizer = PersonSynchronizer(args)
            synchronizer.merge_pair(read_document(person_path), read_document(other_path))
            synchronizer.write_reports([read_document(person_path)])
            source = fake.summarize.call_args.args[0]
            self.assertIn(personal_bio.strip(), source)
            self.assertIn(incoming_bio.strip(), source)
            updated = person_path.read_text(encoding="utf-8")
            self.assertIn(f"## Bio\n\n{summary}\n\n", updated)
            self.assertIn("## Notes\n\nKeep notes.\n", updated)
            second = PersonSynchronizer(args)
            second.merge_pair(read_document(person_path), read_document(other_path))
            self.assertEqual(person_path.read_text(encoding="utf-8"), updated)
            fake.summarize.assert_called_once()
            other_path.write_text(
                f"---\ntags: [person]\nslug: jane-doe\n---\n## Bio\n\n{incoming_bio}New experience.\n",
                encoding="utf-8",
            )
            second.merge_pair(read_document(person_path), read_document(other_path))
            self.assertEqual(fake.summarize.call_count, 2)

    def test_bio_summary_failure_does_not_write_person_file(self):
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Bio\n\nShort bio.\n",
        )
        other_path = self.write_person(
            self.other_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Bio\n\n" + "Technology experience. " * 30,
        )
        original = person_path.read_bytes()
        args = self.arguments()
        args.summarize_bio = True
        fake = Mock()
        fake.summarize.side_effect = BioSummaryError("Provider failed")
        with patch("tools.merge_person_files.BioSummarizer.from_settings", return_value=fake):
            with self.assertRaises(BioSummaryError):
                PersonSynchronizer(args).merge_pair(read_document(person_path), read_document(other_path))
        self.assertEqual(person_path.read_bytes(), original)

    def test_dry_run_bio_summary_reports_result_without_writing_note_or_cache(self):
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Bio\n\nOriginal bio.\n",
        )
        other_path = self.write_person(
            self.other_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Bio\n\n" + "Technology experience. " * 30,
        )
        original = person_path.read_bytes()
        args = self.arguments(dry_run=True)
        args.summarize_bio = True
        fake = Mock()
        fake.summarize.return_value = "Technology professional."
        with patch("tools.merge_person_files.BioSummarizer.from_settings", return_value=fake):
            synchronizer = PersonSynchronizer(args)
            synchronizer.merge_pair(read_document(person_path), read_document(other_path))
            synchronizer.write_reports([read_document(person_path)])
        self.assertEqual(person_path.read_bytes(), original)
        self.assertFalse((self.state_root / "bio_summaries.json").exists())
        self.assertIn("Technology professional.", (self.state_root / "changes_proposed.csv").read_text(encoding="utf-8"))

    def test_new_person_bio_summary_uses_generated_person_slug(self):
        other_path = self.write_person(
            self.other_root, "profile-id",
            "---\ntags: [person]\nslug: profile-id\nfirst_name: Jane\nlast_name: Doe\n---\n## Bio\n\n" + "Technology experience. " * 30,
        )
        args = self.arguments()
        args.summarize_bio = True
        fake = Mock()
        fake.summarize.return_value = "Technology professional."
        with patch("tools.merge_person_files.BioSummarizer.from_settings", return_value=fake):
            synchronizer = PersonSynchronizer(args)
            synchronizer.create_person(read_document(other_path), set())
        self.assertIn("jane-doe", synchronizer.store.bio_summaries)
        self.assertIn("Technology professional.", (self.personal_root / "jane-doe" / "Jane Doe.md").read_text(encoding="utf-8"))

    def test_bio_opt_out_and_short_bios_do_not_call_provider(self):
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n",
        )
        person = read_document(person_path)
        with patch("tools.merge_person_files.BioSummarizer.from_settings") as provider:
            args = self.arguments()
            synchronizer = PersonSynchronizer(args)
            long_raw = person.raw + "## Bio\n\n" + "Technology experience. " * 30
            self.assertEqual(synchronizer.summarize_bio(person, long_raw, ""), long_raw)
            args.summarize_bio = True
            short_raw = person.raw + "## Bio\n\nShort bio.\n"
            self.assertEqual(synchronizer.summarize_bio(person, short_raw, ""), short_raw)
            provider.assert_not_called()

    def test_bio_summary_threshold_is_strict_and_uses_environment(self):
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n",
        )
        person = read_document(person_path)
        args = self.arguments()
        args.summarize_bio = True
        fake = Mock()
        fake.summarize.return_value = "Brief."
        with patch.dict("os.environ", {"AI_SUMMARY_MAX_CHARS": "10"}), patch(
            "tools.merge_person_files.BioSummarizer.from_settings", return_value=fake,
        ):
            synchronizer = PersonSynchronizer(args)
            equal_raw = person.raw + "## Bio\n\n> abcdefghij\n"
            self.assertEqual(synchronizer.summarize_bio(person, equal_raw, ""), equal_raw)
            fake.summarize.assert_not_called()
            long_raw = person.raw + "## Bio\n\n> abcdefghijk\n"
            self.assertIn("Brief.", synchronizer.summarize_bio(person, long_raw, ""))
            fake.summarize.assert_called_once_with("abcdefghijk")

    def test_cli_summary_error_returns_failure_without_applying_merge(self):
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n\n## Bio\n\nOriginal bio.\n",
        )
        self.write_person(
            self.other_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Bio\n\n" + "Technology experience. " * 30,
        )
        with patch(
            "tools.merge_person_files.BioSummarizer.from_settings",
            side_effect=BioSummaryError("Missing credentials; use --do-not-summarize"),
        ), self.assertLogs(level="ERROR") as logs:
            self.assertEqual(main([
                "-e", str(self.personal_root), "-i", str(self.other_root),
                "-t", str(self.state_root), "-p", "jane-doe",
            ]), 1)
        self.assertIn("--do-not-summarize", logs.output[0])
        self.assertIn("Original bio.", person_path.read_text(encoding="utf-8"))
        self.assertNotIn("Technology experience.", person_path.read_text(encoding="utf-8"))

    def arguments(self, dry_run=False):
        return Namespace(
            existing=str(self.personal_root), state_dir=str(self.state_root), dry_run=dry_run,
            bio_similarity=0.70, auto_match_threshold=0.96, review_match_threshold=0.80,
            lookback_days=365,
            summarize_bio=False,
        )

    def write_person(self, root, folder, content):
        path = root / folder
        path.mkdir()
        file_path = path / "Jane Doe.md"
        file_path.write_text(content, encoding="utf-8")
        return file_path

    def test_slug_run_never_discovers_or_reads_unrelated_person_folders(self):
        personal_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n",
        )
        other_path = self.write_person(
            self.other_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\nskills: [Rust]\n---\n",
        )
        for root in (self.personal_root, self.other_root):
            self.write_person(root, "unrelated", "---\ntags: [person]\n- malformed\n---\n")
        registry_path = self.root / "organizations.json"
        registry_path.write_text("[]", encoding="utf-8")
        original_rglob = Path.rglob

        def scoped_rglob(path, pattern):
            self.assertNotIn(path.resolve(), (self.personal_root, self.other_root))
            return original_rglob(path, pattern)

        with patch.object(Path, "rglob", scoped_rglob), patch(
            "tools.merge_person_files.read_document", wraps=read_document,
        ) as reader:
            self.assertEqual(main([
                "-e", str(self.personal_root), "-i", str(self.other_root),
                "-t", str(self.state_root), "--organizations-config", str(registry_path),
                "-p", "jane-doe", "-m",
            ]), 0)

        self.assertEqual({call.args[0] for call in reader.call_args_list}, {personal_path, other_path})
        self.assertIn("skills:\n  - Rust\n", personal_path.read_text(encoding="utf-8"))

    def test_slug_normalization_does_not_scan_unrelated_folders(self):
        personal_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n",
        )
        self.write_person(self.personal_root, "unrelated", "---\ntags: [person]\n- malformed\n---\n")
        with patch("tools.merge_person_files.read_document", wraps=read_document) as reader:
            self.assertEqual(main([
                "-e", str(self.personal_root), "-t", str(self.state_root),
                "-p", "jane-doe", "-m", "-n",
            ]), 0)
        self.assertEqual({call.args[0] for call in reader.call_args_list}, {personal_path})

    def test_slug_discovery_supports_multiple_and_missing_folders(self):
        paths = [
            self.write_person(
                self.personal_root, slug,
                f"---\ntags: [person]\nslug: {slug}\n---\n",
            )
            for slug in ("jane-doe", "john-doe", "unrelated")
        ]
        with patch("tools.merge_person_files.read_document", wraps=read_document) as reader:
            people = discover_people(self.personal_root, {"jane-doe", "john-doe", "missing"})
            self.assertEqual(discover_people(self.personal_root, {"missing"}), [])
        self.assertEqual({person.path for person in people}, set(paths[:2]))
        self.assertEqual({call.args[0] for call in reader.call_args_list}, set(paths[:2]))

    def test_slug_discovery_rejects_paths_outside_person_folders(self):
        for slug in (".", "..", "../unrelated", str(self.personal_root)):
            with self.subTest(slug=slug), self.assertRaises(ValueError):
                discover_people(self.personal_root, {slug})

    def test_combined_slug_and_linkedin_id_still_discovers_both_people(self):
        for slug, linkedin_id in (("jane-doe", "jane-profile"), ("john-doe", "john-profile")):
            self.write_person(
                self.personal_root, slug,
                f"---\ntags: [person]\nslug: {slug}\nlinkedin_id: {linkedin_id}\n---\n",
            )
        with patch(
            "tools.merge_person_files.discover_people", wraps=discover_people,
        ) as discovery, patch(
            "tools.merge_person_files.PersonSynchronizer.normalize_positions",
        ) as normalize:
            self.assertEqual(main([
                "-e", str(self.personal_root), "-t", str(self.state_root),
                "-p", "jane-doe", "--linkedin-id", "john-profile", "-m", "-n",
            ]), 0)
        self.assertIsNone(discovery.call_args.args[1])
        self.assertEqual({person.slug for person in normalize.call_args.args[0]}, {"jane-doe", "john-doe"})

    def test_slug_run_reserves_unscanned_existing_folder_names_when_creating(self):
        personal_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n",
        )
        original = personal_path.read_bytes()
        self.write_person(
            self.other_root, "source-slug",
            "---\ntags: [person]\nslug: source-slug\nfirst_name: Jane\nlast_name: Doe\n---\n",
        )
        self.assertEqual(main([
            "-e", str(self.personal_root), "-i", str(self.other_root),
            "-t", str(self.state_root), "-p", "source-slug",
        ]), 0)
        self.assertEqual(personal_path.read_bytes(), original)
        self.assertTrue((self.personal_root / "jane-doe-2" / "Jane Doe.md").exists())

    def test_merge_changes_only_approved_fields_and_sections(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\nskills:\n  - Python\nprivate_field: keep exactly\n---\n# Jane Doe\n\n## Bio\nA software engineer.\n\n## Notes\nDo not rewrite this section.\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\nskills:\n  - Python\n  - Rust\n---\n# Jane Doe\n\n## Bio\nA software engineer!\n",
        )
        personal, other = discover_people(self.personal_root), discover_people(self.other_root)

        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.match_and_sync(personal, other)

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("  - Python\n  - Rust\nprivate_field: keep exactly\n", updated)
        self.assertIn("## Notes\n\nDo not rewrite this section.\n", updated)
        self.assertIn("## Bio\n\nA software engineer!\n", updated)
        skills_change = next(change for change in synchronizer.changes if change["field"] == "skills")
        self.assertEqual(skills_change["old_value"], '["Python"]')
        self.assertEqual(skills_change["new_value"], '["Python", "Rust"]')

    def test_merge_formats_appended_bio_as_two_quoted_paragraphs(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Bio\n> A labour and media analyst.\n## Life Events\n- \n## Positions\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Bio\nA journalist and consultant.\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn(
            "## Bio\n\n> A labour and media analyst.\n>\n> A journalist and consultant.\n\n## Life Events",
            updated,
        )
        self.assertNotIn("\n>\n>\n", updated)

    def test_merge_removes_empty_quoted_bio_boundaries(self):
        incoming_bio = "> - Resolve business problems using technology"
        for summarize in (False, True):
            for personal_bio in ("> ", ">\n>", "> \n>\n" + incoming_bio + "\n> "):
                with self.subTest(summarize=summarize, personal_bio=personal_bio):
                    personal_path = self.personal_root / "Jane Doe.md"
                    other_path = self.other_root / "Jane Doe.md"
                    header = "---\ntags: [person]\nslug: jane-doe\n---\n"
                    personal_path.write_text(
                        header + f"## Bio\n\n{personal_bio}\n\n## Notes\n\nKeep notes.\n",
                        encoding="utf-8",
                    )
                    other_path.write_text(
                        header + f"## Bio\n\n> \n{incoming_bio}\n>\n", encoding="utf-8",
                    )
                    original_incoming = other_path.read_bytes()
                    args = self.arguments()
                    args.summarize_bio = summarize
                    synchronizer = PersonSynchronizer(args)
                    with patch("tools.merge_person_files.BioSummarizer.from_settings") as provider:
                        synchronizer.merge_pair(read_document(personal_path), read_document(other_path))
                        updated = personal_path.read_text(encoding="utf-8")
                        self.assertEqual(section_content(updated, "## Bio").strip(), incoming_bio)
                        self.assertIn("## Notes\n\nKeep notes.\n", updated)
                        synchronizer.merge_pair(read_document(personal_path), read_document(other_path))
                        self.assertEqual(personal_path.read_text(encoding="utf-8"), updated)
                        provider.assert_not_called()
                    self.assertEqual(other_path.read_bytes(), original_incoming)

    def test_merge_preserves_internal_quoted_bio_paragraph_breaks(self):
        header = "---\ntags: [person]\nslug: jane-doe\n---\n"
        personal_path = self.write_person(
            self.personal_root, "jane-doe",
            header + "## Bio\n\n> \n> First paragraph.\n>\n> Second paragraph.\n>\n",
        )
        other_path = self.write_person(self.other_root, "jane-doe", header)
        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.merge_pair(read_document(personal_path), read_document(other_path))
        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("## Bio\n\n> First paragraph.\n>\n> Second paragraph.\n", updated)
        self.assertNotIn("> Second paragraph.\n>", updated)

    def test_create_person_trims_quoted_bio_boundaries(self):
        other_path = self.write_person(
            self.other_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n"
            "## Bio\n\n> \n>\n> - Resolve business problems using technology\n>\n"
            "\n## Notes\n\nKeep notes.\n",
        )
        original_incoming = other_path.read_bytes()
        for summarize in (False, True):
            with self.subTest(summarize=summarize):
                args = self.arguments()
                args.summarize_bio = summarize
                PersonSynchronizer(args).create_person(read_document(other_path), set())
                created = read_document(self.personal_root / "jane-doe" / "Jane Doe.md")
                self.assertEqual(
                    section_content(created.raw, "## Bio").strip(),
                    "> - Resolve business problems using technology",
                )
                self.assertIn("## Notes\n\nKeep notes.\n", created.raw)
                self.assertEqual(other_path.read_bytes(), original_incoming)

    def test_merge_updates_last_updated_only_when_content_changes(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\nlast_updated: 2020-01-01\nskills:\n  - Python\n---\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\nskills:\n  - Python\n  - Rust\n---\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn(f"last_updated: {dt.date.today().isoformat()}\n", updated)

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        self.assertEqual(personal_path.read_text(encoding="utf-8"), updated)

    def test_merge_adds_incoming_organizations_without_removing_personal_ones(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\norganizations:\n  - acme\n---\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\norganizations:\n  - acme\n  - globex\n---\n",
        )

        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("organizations:\n  - acme\n  - globex\n", updated)
        change = next(change for change in synchronizer.changes if change["field"] == "organizations")
        self.assertEqual(change["old_value"], '["acme"]')
        self.assertEqual(change["new_value"], '["acme", "globex"]')

    def test_merge_ignores_long_and_educational_summary_organization_slugs(self):
        ignored = [
            "a" * 65,
            "3-educational-experiences-at-university-of-toronto-and-2-other-schools",
            "2-educational-experiences",
        ]
        person_path = self.write_person(
            self.personal_root, "amelia-cantwell",
            "---\ntags: [person]\nslug: amelia-cantwell\norganizations: [acme]\n---\n",
        )
        other_path = self.write_person(
            self.other_root, "amelia-cantwell",
            "---\ntags: [person]\nslug: amelia-cantwell\nlinkedin_id: amelia-cantwell-142880362\n"
            f"organizations: {json.dumps([*ignored, 'b' * 64, 'university-of-toronto'])}\n---\n",
        )
        PersonSynchronizer(self.arguments()).merge_pair(read_document(person_path), read_document(other_path))
        organizations = read_document(person_path).frontmatter["organizations"]
        self.assertEqual(organizations, ["acme", "b" * 64, "university-of-toronto"])

    def test_created_person_ignores_invalid_organization_slugs(self):
        other_path = self.write_person(
            self.other_root, "amelia-cantwell",
            "---\ntags: [person]\nslug: amelia-cantwell\nfirst_name: Amelia\nlast_name: Cantwell\n"
            f"organizations: {json.dumps(['a' * 65, '2-educational-experiences', 'acme'])}\n---\n",
        )
        PersonSynchronizer(self.arguments()).create_person(read_document(other_path), set())
        created = read_document(self.personal_root / "amelia-cantwell" / "Amelia Cantwell.md")
        self.assertEqual(created.frontmatter["organizations"], ["acme"])

    def test_merge_inserts_missing_fields_in_person_template_order(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nfirst_name: Jane\nlast_name: Doe\nslug: jane-doe\n---\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nfirst_name: Jane\nlast_name: Doe\nslug: jane-doe\nlinkedin_id: jane-doe\nmobile: 555-0100\nemail: jane@example.com\n---\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        frontmatter = personal_path.read_text(encoding="utf-8").split("---", 2)[1]
        merged_fields = [
            line.partition(":")[0]
            for line in frontmatter.splitlines()
            if line and not line[0].isspace()
        ]
        inserted_fields = [
            field for field in merged_fields
            if field in {"email", "mobile", "linkedin_id"}
        ]
        self.assertEqual(inserted_fields, ["email", "mobile", "linkedin_id"])
        self.assertEqual(
            [field for field in FRONTMATTER_FIELD_ORDER if field in {"email", "mobile", "linkedin_id"}],
            inserted_fields,
        )

    def test_nested_incoming_directory_is_excluded_from_existing_people(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\norganizations:\n  - acme\n---\n",
        )
        incoming_root = self.personal_root / "People-LinkedIn"
        incoming_root.mkdir()
        self.write_person(
            incoming_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\norganizations:\n  - globex\n---\n",
        )
        source_root = self.personal_root / "People-Source"
        source_root.mkdir()
        self.write_person(
            source_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n",
        )
        state_root = self.personal_root / "people_sync_state"
        backup_root = state_root / "backups" / "2026-08-30"
        backup_root.mkdir(parents=True)
        self.write_person(
            backup_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n",
        )

        self.assertEqual(main([
            "--existing", str(self.personal_root),
            "--incoming", str(incoming_root),
            "--state-dir", str(state_root),
            "--slug", "jane-doe",
        ]), 0)

        self.assertIn("organizations:\n  - acme\n  - globex\n", personal_path.read_text(encoding="utf-8"))

    def test_normalize_positions_converts_only_fenced_description(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n* Engineer, [[Acme]], 2023-01-02\n\n    ```\n    Built systems\n    Led projects\n    ```\n\n- Manager, [[Acme]], 2024-01-02\n```\nManaged teams\n```\n\n## Notes\n- A code sample\n\n  ```\n  remain unchanged\n  ```\n",
        )
        synchronizer = PersonSynchronizer(self.arguments())

        synchronizer.normalize_positions(discover_people(self.personal_root))

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("  > Built systems Led projects\n", updated)
        self.assertIn("  > Managed teams\n", updated)
        self.assertNotIn("```", updated.split("## Notes", 1)[0])
        self.assertIn("## Notes\n\n- A code sample\n\n  ```\n  remain unchanged\n  ```\n", updated)

    def test_normalize_positions_renders_single_paragraph_without_bullet(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [[Acme]], 2024-01\n```\nDesigned systems\nand led projects.\n```\n",
        )

        PersonSynchronizer(self.arguments()).normalize_positions(discover_people(self.personal_root))

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("  > Designed systems and led projects.\n", updated)
        self.assertNotIn("  > - Designed systems", updated)

    def test_normalize_positions_removes_legacy_single_bullet_description(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [[Acme]], 2024-01\n\n  > - Designed systems.\n",
        )

        PersonSynchronizer(self.arguments()).normalize_positions(discover_people(self.personal_root))

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("  > Designed systems.\n", updated)
        self.assertNotIn("  > - Designed systems.", updated)

    def test_normalize_positions_repairs_quoted_position_and_unclosed_fence(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Research Intern, [[OUSA]], 2016-05 to 2016-08\n\n> Transition & Mentorship Program Manager, [[McMaster University]], [[Hamilton]], 2017-05 to 2019-04\n>\n> Courses developed communication skills\n- Developed arguments through theoretical frameworks\n- Facilitated group dynamics\n\n```\n- Master of Education, [[University of Toronto]], 2018 to 2020\n- Alumni Engagement Officer, [[University of Toronto]], [[Toronto]], 2023-02 #current\n",
        )

        PersonSynchronizer(self.arguments()).normalize_positions(discover_people(self.personal_root))

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("- Transition & Mentorship Program Manager, [[McMaster University]], [[Hamilton]], 2017-05 to 2019-04", updated)
        self.assertIn("  > - Developed arguments through theoretical frameworks", updated)
        self.assertIn("- Master of Education, [[University of Toronto]], 2018 to 2020", updated)
        self.assertIn("- Alumni Engagement Officer, [[University of Toronto]], [[Toronto]], 2023-02 #current", updated)
        self.assertNotIn("```", updated)

    def test_normalize_positions_repairs_nested_role_bullets_and_links_plain_organization(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n"
            "## Bio\n> Personal bio.\n"
            "## Positions\n"
            "- Bachelor of Arts - BA Journalism, [[Toronto Metropolitan University]]\n"
            "    \n"
            "- News Producer, [CBC](CBC), 1983-04 to 2019-06, Toronto\n"
            "  > Did a wide range of senior journalistic functions.\n"
            "- Coordinator, Canadian Media Guild/CWA Canada/IATSE, 2017-10 to #current, Toronto\n"
            "\t - Working to secure a collective voice for factual TV workers.\n"
            " - - Member (Volunteer), [Federal Labour Standards Advisory Committee](Federal Labour Standards Advisory Committee), 2018-09 to #current\n"
            "\t - Part of a union-management-government committee to improve labour standards.\n"
            "- Family Advisory Committee (Volunteer), Kerry's Place Autism Services, 2019-01 to 2019\n"
            "> Now serving on the organization's Family Advisory Committee.\n"
            ">\n"
            "## Life events\n- \n",
        )

        PersonSynchronizer(self.arguments()).normalize_positions(discover_people(self.personal_root))

        updated = personal_path.read_text(encoding="utf-8")
        positions = updated.split("## Positions\n", 1)[1].split("## Life events", 1)[0]
        self.assertIn(
            "- Bachelor of Arts - BA Journalism, [[Toronto Metropolitan University]]\n"
            "- News Producer, [[CBC]], 1983-04 to 2019-06, Toronto",
            positions,
        )
        self.assertIn(
            "- Member (Volunteer), [[Federal Labour Standards Advisory Committee]], 2018-09 to #current",
            positions,
        )
        self.assertNotIn("- - Member", positions)
        self.assertIn("  > Working to secure a collective voice for factual TV workers.", positions)
        self.assertIn("  > Part of a union-management-government committee", positions)
        self.assertIn(
            "- Family Advisory Committee (Volunteer), Kerry's Place Autism Services, 2019-01 to 2019",
            positions,
        )
        self.assertNotIn("Family Advisory Committee.\n  >", positions)
        self.assertIn("Family Advisory Committee.\n\n## Life events", updated)

    def test_normalize_positions_preserves_undated_top_level_position(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Consultant/Developer Contractor, [[Sage Computing]], Toronto, 2002-10 to 2004\n- Web Consulting - Define parameters of project with time estimates\n\n> - Client and Server components development in Java\n",
        )

        PersonSynchronizer(self.arguments()).normalize_positions(discover_people(self.personal_root))

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("- Web Consulting - Define parameters of project with time estimates", updated)
        self.assertNotIn("  > - Web Consulting", updated)
        self.assertIn("\n\n  > Client and Server components development in Java\n", updated)

    def test_normalize_positions_quotes_blank_lines_within_description(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- J2EE Systems Developer, [[Navantis]], Toronto, 2003-04 to 2003-07\n\n> - Technical lead in building portal subsystems for Honda Canada\n\n> - Indexed document management administration system\n> - Websphere 5.0, WSAD, DB2 7.2\n",
        )

        PersonSynchronizer(self.arguments()).normalize_positions(discover_people(self.personal_root))

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("  > - Technical lead in building portal subsystems for Honda Canada\n  >\n  > - Indexed document", updated)
        self.assertNotIn("Honda Canada\n\n  > - Indexed", updated)

    def test_normalize_positions_orders_entries_chronologically(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Manager, [[Acme]], 2024-01\n- Engineer, [[Acme]], 2023-01\n",
        )

        PersonSynchronizer(self.arguments()).normalize_positions(discover_people(self.personal_root))

        updated = personal_path.read_text(encoding="utf-8")
        self.assertLess(updated.index("Engineer, [[Acme]], 2023-01"), updated.index("Manager, [[Acme]], 2024-01"))

    def test_normalize_positions_removes_blank_lines_between_plain_entries(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n\n\n\n- Manager, [[Acme]], 2024-01\n\n\n- Engineer, [[Acme]], 2023-01\n",
        )

        PersonSynchronizer(self.arguments()).normalize_positions(discover_people(self.personal_root))

        positions = personal_path.read_text(encoding="utf-8").split("## Positions", 1)[1]
        self.assertTrue(positions.startswith("\n\n- Engineer, [[Acme]], 2023-01"))
        self.assertIn("2023-01\n- Manager, [[Acme]], 2024-01", positions)
        self.assertNotIn("\n\n\n", positions)

    def test_render_positions_keeps_blank_lines_only_around_descriptions(self):
        for line_end in ("\n", "\r\n"):
            with self.subTest(line_end=repr(line_end)):
                blocks = [
                    "- First, [[Acme]], 2020\n\n\n",
                    "- Second, [[Acme]], 2021\n\n\n  > Description\n  >\n  > Another paragraph\n\n\n",
                    "- Third, [[Acme]], 2022\n  > Another description\n",
                    "- Fourth, [[Acme]], 2023\n\n",
                    "- Fifth, [[Acme]], 2024\n",
                ]
                expected = (
                    "- First, [[Acme]], 2020\n"
                    "- Second, [[Acme]], 2021\n\n"
                    "  > Description\n  >\n  > Another paragraph\n\n"
                    "- Third, [[Acme]], 2022\n\n"
                    "  > Another description\n\n"
                    "- Fourth, [[Acme]], 2023\n"
                    "- Fifth, [[Acme]], 2024\n"
                )
                self.assertEqual(
                    render_position_blocks(blocks, line_end),
                    expected.replace("\n", line_end),
                )

    def test_merge_positions_does_not_add_blank_lines_between_plain_entries(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n- First, [[Acme]], 2020\n\n\n- Second, [[Acme]], 2021\n  > Description\n\n## Notes\nKeep exactly.\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n- Third, [[Globex]], 2022\n\n- Fourth, [[Initech]], 2023\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn(
            "## Positions\n\n"
            "- First, [[Acme]], 2020\n"
            "- Second, [[Acme]], 2021\n\n"
            "  > Description\n\n"
            "- Third, [[Globex]], 2022\n"
            "- Fourth, [[Initech]], 2023\n\n"
            "## Notes\n\nKeep exactly.\n",
            updated,
        )
        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )
        self.assertEqual(personal_path.read_text(encoding="utf-8"), updated)

    def test_normalize_positions_leaves_undated_entries_in_place(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- The world of hard knocks - tough experience, [[Swansea University / Prifysgol Abertawe]]\n- B.Sc - Economics, [[Swansea University]]\n- Manager, [[Acme]], 2024-01\n- Engineer, [[Acme]], 2023-01\n## Notes\nKeep this note.\n",
        )

        PersonSynchronizer(self.arguments()).normalize_positions(discover_people(self.personal_root))

        updated = personal_path.read_text(encoding="utf-8")
        hard_knocks = "The world of hard knocks - tough experience"
        economics = "B.Sc - Economics"
        engineer = "Engineer, [[Acme]], 2023-01"
        manager = "Manager, [[Acme]], 2024-01"
        self.assertLess(updated.index(hard_knocks), updated.index(economics))
        self.assertLess(updated.index(economics), updated.index(engineer))
        self.assertLess(updated.index(engineer), updated.index(manager))
        self.assertIn("- Manager, [[Acme]], 2024-01\n\n## Notes", updated)

    def test_merge_orders_undated_education_by_qualification_before_dated_positions(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Director, [[Acme]], 2024-01\n- Engineer, [[Acme]], 2023-01\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Doctorate in Computer Science, [[University D]]\n- Masters of Engineering, [[University M]]\n- BEng, Engineering, [[University B]]\n- Ph.D., Computer Science, [[University D2]]\n- MASc, Applied Science, [[University M2]]\n- Bachelor of Arts, [[University B2]]\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertLess(updated.index("BEng, Engineering"), updated.index("Masters of Engineering"))
        self.assertLess(updated.index("Bachelor of Arts"), updated.index("MASc, Applied Science"))
        self.assertLess(updated.index("Masters of Engineering"), updated.index("Doctorate in Computer Science"))
        self.assertLess(updated.index("MASc, Applied Science"), updated.index("Ph.D., Computer Science"))
        self.assertLess(updated.index("Ph.D., Computer Science"), updated.index("Engineer, [[Acme]], 2023-01"))
        self.assertLess(updated.index("Engineer, [[Acme]], 2023-01"), updated.index("Director, [[Acme]], 2024-01"))

    def test_merge_orders_undated_be_ba_bsc_before_masters_and_phd(self):
        degrees = [
            "- PhD, Electrical Engineering, [[Doctoral University]]",
            "- Master of Business Administration, Finance, [[SVKM]], [[Narsee Monjee Institute of Management Studies]]",
            "- Application of Business Analytics, Business Analytics Certificate Program from [[Dun & Bradstreet]] and [[EduPristine]]",
            "- BE, Electrical & Electronics, [[Anna University Chennai]]",
            "- BA, Arts, [[Arts University]]",
            "- BSc, Science, [[Science University]]",
            "- Masters, Engineering, [[Masters University]]",
        ]
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n",
        )
        other_path = self.write_person(
            self.other_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n" + "\n".join(degrees) + "\n",
        )
        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.merge_pair(read_document(person_path), read_document(other_path))
        synchronizer.normalize_positions([read_document(person_path)])
        updated = person_path.read_text(encoding="utf-8")
        for bachelor in ("BE, Electrical", "BA, Arts", "BSc, Science"):
            self.assertLess(updated.index(bachelor), updated.index("Master of Business"))
            self.assertLess(updated.index(bachelor), updated.index("Masters, Engineering"))
        self.assertLess(updated.index("Master of Business"), updated.index("PhD, Electrical"))
        self.assertLess(updated.index("Masters, Engineering"), updated.index("PhD, Electrical"))

    def test_combined_merge_and_normalize_imports_skills_and_bio(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\nskills:\n  - Python\n---\n# Jane Doe\n\n![[jane-doe.jpg|100]]\n\n## Positions\n- Manager, [[Acme]], 2024-01\n```\nManaged teams\n```\n\n- Engineer, [[Acme]], 2023-01\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\nskills:\n  - Python\n  - Rust\n---\n## Bio\nA software engineer.\n",
        )

        self.assertEqual(main([
            "--existing", str(self.personal_root),
            "--incoming", str(self.other_root),
            "--normalize-positions",
            "--state-dir", str(self.state_root),
        ]), 0)

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("  - Rust\n", updated)
        self.assertIn("![[jane-doe.jpg|100]]\n\n## Bio\n\nA software engineer.", updated)
        self.assertNotIn("```", updated)
        self.assertIn("## Positions\n\n- Engineer, [[Acme]], 2023-01", updated)
        self.assertLess(updated.index("Engineer, [[Acme]], 2023-01"), updated.index("Manager, [[Acme]], 2024-01"))

    def test_merge_can_add_a_missing_frontmatter_field(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nlast_name: Doe\n---\n## Bio\n\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Bio\n\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("first_name: Jane\n", updated)

    def test_merge_adds_missing_linkedin_id_without_review(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\nlinkedin_id: jane-doe-123\n---\n",
        )

        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("linkedin_id: jane-doe-123\n", updated)
        self.assertFalse(synchronizer.reviews)

    def test_merge_queues_changed_email_for_review(self):
        personal_path = self.write_person(
            self.personal_root,
            "mark-leonard",
            "---\ntags: [person]\nslug: mark-leonard\nfirst_name: Mark\nlast_name: Leonard\nemail: old@example.com\n---\n",
        )
        self.write_person(
            self.other_root,
            "mark-leonard",
            "---\ntags: [person]\nslug: mark-leonard\nfirst_name: Mark\nlast_name: Leonard\nemail: new@example.com\n---\n",
        )

        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        self.assertIn("email: old@example.com\n", personal_path.read_text(encoding="utf-8"))
        self.assertEqual(len(synchronizer.reviews), 1)
        self.assertEqual(synchronizer.reviews[0]["field"], "email")
        self.assertEqual(synchronizer.reviews[0]["type"], "contact_info")
        self.assertEqual(synchronizer.reviews[0]["personal"], "old@example.com")
        self.assertEqual(synchronizer.reviews[0]["other"], "new@example.com")

    def test_position_date_review_includes_existing_incoming_and_suggested_lines(self):
        self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [[Acme]], 2002-03 to 2003-10\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [[Acme]], 2002-04 to 2003-11\n",
        )

        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        self.assertEqual(len(synchronizer.reviews), 1)
        review = synchronizer.reviews[0]
        self.assertEqual(review["existing_line"], "- Engineer, [[Acme]], 2002-03 to 2003-10")
        self.assertEqual(review["incoming_line"], "- Engineer, [[Acme]], 2002-04 to 2003-11")
        self.assertEqual(review["suggested_line"], "- Engineer, [[Acme]], 2002-04 to 2003-10")
        prompt = review_context(review)
        self.assertIn("Existing:", prompt)
        self.assertIn("Incoming:", prompt)
        self.assertIn("Suggested:", prompt)

    def test_distinct_roles_at_same_organization_are_not_merged(self):
        senior_line = "- Senior Software Engineer, [[Infor]], [[Victoria]], 2018-12 to 2019-05"
        for index, (existing_line, incoming_line) in enumerate((
            (senior_line, "- Principal Software Engineer, [[Infor]], [[Victoria]], 2019-05 to 2020-11"),
            (senior_line, "- Principal Software Engineer, [[Infor]], [[Victoria]], 2019-04 to 2020-11"),
            (senior_line, "- Senior Software Engineer, [[Infor]], [[Victoria]], 2019-05 to 2020-11"),
            (
                "- Development Team Lead, [[Infor]], [[Victoria]], 2020-11 to 2022-02",
                "- Software Development Manager, [[Infor]], [[Victoria]], 2022-02 to 2026-04",
            ),
        )):
            with self.subTest(existing_line=existing_line, incoming_line=incoming_line):
                person = read_document(self.write_person(
                    self.personal_root, f"existing-{index}",
                    "---\ntags: [person]\nslug: brad-barclay\n---\n## Positions\n"
                    f"{existing_line}\n\n  > Senior role description.\n",
                ))
                other = read_document(self.write_person(
                    self.other_root, f"incoming-{index}",
                    "---\ntags: [person]\nslug: brad-barclay\n---\n## Positions\n"
                    f"{incoming_line}\n\n  > Incoming role description.\n",
                ))
                synchronizer = PersonSynchronizer(self.arguments())
                merged = synchronizer.merge_positions(person, other, person.raw)
                self.assertIn(existing_line, merged)
                self.assertIn(incoming_line, merged)
                self.assertIn("Senior role description.", merged)
                self.assertIn("Incoming role description.", merged)
                self.assertEqual(synchronizer.reviews, [])
                person.path.write_text(merged, encoding="utf-8")
                synchronizer.normalize_positions([read_document(person.path)])
                normalized = person.path.read_text(encoding="utf-8")
                self.assertEqual(normalized.count(existing_line), 1)
                self.assertEqual(normalized.count(incoming_line), 1)

    def test_shared_month_preserves_first_role_and_reviews_only_later_role_changes(self):
        first = (
            "- Technical Director, Enterprise Solution Architecture, [[BlackBerry]], "
            "2007-07 to 2008-12"
        )
        second = (
            "- Sr. Director, Enterprise Business Intelligence and Mobility, [[BlackBerry]], "
            "Alpharetta, Georgia, 2008-12 to 2013-08"
        )
        for end in ("2013-08", "2013-09"):
            with self.subTest(incoming_end=end):
                person_path = self.write_person(
                    self.personal_root, f"lori-miles-{end}",
                    "---\ntags: [person]\nslug: lori-miles\n---\n## Positions\n"
                    f"{first}\n\n  > First description.\n\n{second}\n",
                )
                incoming = second.replace("2013-08", end)
                other_path = self.write_person(
                    self.other_root, f"lori-miles-{end}",
                    f"---\ntags: [person]\nslug: lori-miles\n---\n## Positions\n{incoming}\n",
                )
                synchronizer = PersonSynchronizer(self.arguments())
                synchronizer.merge_pair(read_document(person_path), read_document(other_path))
                updated = person_path.read_text(encoding="utf-8")
                self.assertEqual(updated.count(first), 1)
                self.assertEqual(updated.count(second), 1)
                self.assertIn("First description.", updated)
                if end == "2013-08":
                    self.assertEqual(synchronizer.reviews, [])
                else:
                    self.assertEqual(len(synchronizer.reviews), 1)
                    item = synchronizer.reviews[0]
                    self.assertEqual(item["type"], "position_date")
                    self.assertEqual(item["existing_line"], second)
                    self.assertEqual(item["incoming_line"], incoming)
                    self.assertEqual(item["suggested_line"], incoming)
                    synchronizer.write_reports([read_document(person_path)])
                    with patch("tools.merge_person_files.read_review_command", return_value="s"):
                        review_pending(self.arguments())
                    updated = person_path.read_text(encoding="utf-8")
                    self.assertEqual(updated.count(first), 1)
                    self.assertIn("First description.", updated)
                    self.assertEqual(updated.count(incoming), 1)
                    self.assertNotIn(second, updated)

    def test_position_date_ranges_must_overlap_not_just_touch(self):
        for left, right, expected in (
            (["2018-12", "2019-05"], ["2019-05", "2020-11"], False),
            (["2020-11", "2022-02"], ["2022-02", "2026-04"], False),
            (["2019-10-21", "2020-11-13"], ["2020-11-13", "2021-03"], False),
            (["2018-12", "2019-05"], ["2019-06", "2020-11"], False),
            (["2018-12", "2019-05"], ["2019-04", "2020-11"], True),
            (["2019-05", "2019-05"], ["2019-05", "2019-05"], True),
            (["2019-05"], ["2019-05", "2020-11"], True),
        ):
            with self.subTest(left=left, right=right):
                self.assertEqual(dates_overlap(left, right), expected)
                self.assertEqual(dates_overlap(right, left), expected)

    def test_exact_end_date_start_date_handoff_keeps_both_positions_without_review(self):
        first = (
            "- Technical Lead, Customer Prem, [[Cogeco Connexion]], Burlington, Ontario, "
            "2019-10-21 to 2020-11-13, reported to [[Dominique Buslot]]"
        )
        second = (
            "- Technical Lead, Customer Prem, [[Cogeco Connexion]], Burlington, Ontario, "
            "2020-11-13 to 2021-03, reported to [[Gustavo Sanchez]]"
        )
        person_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n"
            f"{first}\n",
        )
        other_path = self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n"
            f"{second}\n",
        )
        synchronizer = PersonSynchronizer(self.arguments())

        synchronizer.merge_pair(read_document(person_path), read_document(other_path))

        updated = person_path.read_text(encoding="utf-8")
        self.assertIn(first, updated)
        self.assertIn(second, updated)
        self.assertEqual(len([item for item in synchronizer.reviews if item["type"] == "position_adjacent"]), 0)

    def test_existing_adjacent_positions_are_preserved_without_review(self):
        lines = [
            "- VP, Engineering, Executives, [[NewStep Networks]], Ottawa, Ontario, "
            "2002 to 2008-01, reported to [[Neil Baimel]]",
            "- VP, Engineering, Executives, [[NewStep Networks]], Toronto, "
            "2008-01-18 to 2008-03, reported to [[Peter Vicars]]",
            "- VP, Architectures and Founder, [[NewStep Networks]], Toronto, "
            "2008-03 to 2008-06-17, reported to [[Peter Vicars]] #laid-off",
        ]
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n"
            + "\n".join(lines) + "\n\n## Notes\n\nKeep notes.\n",
        )
        other_path = self.write_person(
            self.other_root, "jane-doe", "---\ntags: [person]\nslug: jane-doe\n---\n",
        )
        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.merge_pair(read_document(person_path), read_document(other_path))
        self.assertEqual(synchronizer.reviews, [])
        synchronizer.merge_pair(read_document(person_path), read_document(other_path))
        self.assertEqual(synchronizer.store.pending, [])
        synchronizer.write_reports([read_document(person_path)])
        with patch("tools.merge_person_files.read_review_command") as read_command:
            self.assertEqual(review_pending(self.arguments()), 0)
        read_command.assert_not_called()
        updated = person_path.read_text(encoding="utf-8")
        for line in lines:
            self.assertEqual(updated.count(line), 1)
        self.assertIn("## Notes\n\nKeep notes.\n", updated)
        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.merge_pair(read_document(person_path), read_document(other_path))
        self.assertEqual(synchronizer.store.pending, [])

    def test_normalization_preserves_adjacent_positions_without_review(self):
        first = "- Engineer, [[Acme]], 2002-01 to 2003-10"
        second = "- Manager, [[Acme]], 2003-10-15 to 2005-01"
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            f"---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n{first}\n{second}\n",
        )
        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.normalize_positions([read_document(person_path)])
        self.assertEqual(synchronizer.reviews, [])
        synchronizer.write_reports([read_document(person_path)])
        with patch("tools.merge_person_files.read_review_command") as read_command:
            review_pending(self.arguments())
        read_command.assert_not_called()
        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.normalize_positions([read_document(person_path)])
        self.assertEqual(synchronizer.reviews, [])
        self.assertEqual(synchronizer.store.pending, [])
        self.assertIn(first, person_path.read_text(encoding="utf-8"))
        self.assertIn(second, person_path.read_text(encoding="utf-8"))

    def test_adjacent_positions_in_personal_only_and_created_notes_need_no_review(self):
        content = (
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n"
            "## Positions\n- Engineer, [[Acme]], 2002-01 to 2003-10\n"
            "- Manager, [[Acme]], 2003-10 to 2005-01\n"
        )
        personal_path = self.write_person(self.personal_root, "jane-doe", content)
        synchronizer = PersonSynchronizer(self.arguments(dry_run=True))
        synchronizer.match_and_sync([read_document(personal_path)], [])
        self.assertEqual(synchronizer.reviews, [])
        self.assertEqual(personal_path.read_text(encoding="utf-8"), content)
        self.assertFalse(self.state_root.exists())
        other_path = self.write_person(self.other_root, "jane-doe", content)
        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.create_person(read_document(other_path), {"jane-doe"})
        self.assertEqual(synchronizer.reviews, [])
        created = (self.personal_root / "jane-doe-2" / "Jane Doe.md").read_text(encoding="utf-8")
        self.assertIn("- Engineer, [[Acme]], 2002-01 to 2003-10", created)
        self.assertIn("- Manager, [[Acme]], 2003-10 to 2005-01", created)

    def test_separate_positions_do_not_require_review(self):
        synchronizer = PersonSynchronizer(self.arguments())
        person_path = self.write_person(
            self.personal_root, "jane-doe", "---\ntags: [person]\nslug: jane-doe\n---\n",
        )
        person = read_document(person_path)
        for index, (first, second) in enumerate((
            ("- Engineer, [[Acme]], 2002-01 to 2003-10", "- Manager, [[Other]], 2003-10 to 2005-01"),
            ("- Bachelor, [[Acme]], 2002-01 to 2003-10", "- Master, [[Acme]], 2003-10 to 2005-01"),
            ("- Engineer, [[Acme]], 2002 to 2003", "- Manager, [[Acme]], 2003 to 2005"),
            ("- Engineer, [[Acme]], 2002-01 to 2003-10", "- Manager, [[Acme]], 2003-11 to 2005-01"),
        )):
            with self.subTest(first=first, second=second):
                raw = person.raw + "## Positions\n" + first + "\n" + second + "\n"
                other = read_document(self.write_person(
                    self.other_root, f"jane-doe-{index}", "---\ntags: [person]\nslug: jane-doe\n---\n",
                ))
                merged = synchronizer.merge_positions(person, other, raw)
                self.assertIn(first, merged)
                self.assertIn(second, merged)
                self.assertEqual(synchronizer.reviews, [])

    def test_legacy_adjacent_reviews_are_discarded_without_editing_positions(self):
        first = "- Engineer, [[Acme]], 2002-01 to 2003-10"
        second = "- Manager, [[Acme]], 2003-10 to 2005-01"
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n"
            f"{first}\n\n  > First description.\n\n{second}\n\n  > Second description.\n",
        )
        legacy_review = {
            "slug": "jane-doe", "name": "Jane Doe", "path": str(person_path),
            "field": "position:adjacent:old", "type": "position_adjacent",
            "existing_line": first, "incoming_line": second, "suggested_line": second,
            "first_block": first, "second_block": second, "other_hash": source_hash([first, second]),
        }
        unrelated = {**legacy_review, "slug": "someone-else"}
        self.state_root.mkdir()
        pending_path = self.state_root / "pending_review.json"
        pending_path.write_text(json.dumps([legacy_review, unrelated]), encoding="utf-8")
        original = person_path.read_bytes()
        with patch("tools.merge_person_files.read_review_command") as read_command:
            review_pending(self.arguments(), {"jane-doe"})
        read_command.assert_not_called()
        self.assertEqual(person_path.read_bytes(), original)
        self.assertEqual(json.loads(pending_path.read_text(encoding="utf-8")), [unrelated])

    def test_sync_and_normalization_discard_scoped_legacy_reviews_with_dry_run_safety(self):
        content = (
            "---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n\n"
            "- Engineer, [[Acme]], 2002-01 to 2003-10\n"
            "- Manager, [[Acme]], 2003-10 to 2005-01\n"
        )
        person_path = self.write_person(self.personal_root, "jane-doe", content)
        other_path = self.write_person(self.other_root, "jane-doe", content)
        legacy = {
            "slug": "jane-doe", "field": "position:adjacent:old",
            "type": "position_adjacent", "other_hash": source_hash("old"),
        }
        unrelated = {**legacy, "slug": "someone-else"}
        contact = {
            "slug": "jane-doe", "field": "email", "type": "contact_info",
            "other_hash": source_hash("email"),
        }
        self.state_root.mkdir()
        pending_path = self.state_root / "pending_review.json"
        decisions_path = self.state_root / "field_decisions.json"
        decisions_path.write_text(json.dumps({"jane-doe:email": {"decision": "kept_personal"}}), encoding="utf-8")
        original_decisions = decisions_path.read_bytes()
        for operation in ("merge", "normalize", "personal_only"):
            for dry_run in (True, False):
                with self.subTest(operation=operation, dry_run=dry_run):
                    pending_path.write_text(json.dumps([legacy, unrelated, contact]), encoding="utf-8")
                    original_pending = pending_path.read_bytes()
                    original_person = person_path.read_bytes()
                    synchronizer = PersonSynchronizer(self.arguments(dry_run=dry_run))
                    person = read_document(person_path)
                    if operation == "merge":
                        synchronizer.merge_pair(person, read_document(other_path))
                    elif operation == "normalize":
                        synchronizer.normalize_positions([person])
                    else:
                        synchronizer.match_and_sync([person], [])
                    self.assertEqual(synchronizer.store.pending, [unrelated, contact])
                    synchronizer.write_reports([read_document(person_path)])
                    if dry_run:
                        self.assertEqual(pending_path.read_bytes(), original_pending)
                        self.assertEqual(person_path.read_bytes(), original_person)
                    else:
                        self.assertEqual(json.loads(pending_path.read_text(encoding="utf-8")), [unrelated, contact])
                    self.assertEqual(decisions_path.read_bytes(), original_decisions)
                    positions = section_content(person_path.read_text(encoding="utf-8"), "## Positions")
                    self.assertIn("- Engineer, [[Acme]], 2002-01 to 2003-10", positions)
                    self.assertIn("- Manager, [[Acme]], 2003-10 to 2005-01", positions)

    def test_sync_removes_invalid_stored_position_review_only_for_scoped_person(self):
        existing_line = "- Senior Software Engineer, [[Infor]], [[Victoria]], 2018-12 to 2019-05"
        incoming_line = "- Principal Software Engineer, [[Infor]], [[Victoria]], 2019-05 to 2020-11"
        personal_path = self.write_person(
            self.personal_root, "brad-barclay",
            f"---\ntags: [person]\nslug: brad-barclay\n---\n## Positions\n{existing_line}\n",
        )
        self.write_person(
            self.other_root, "brad-barclay",
            f"---\ntags: [person]\nslug: brad-barclay\n---\n## Positions\n{incoming_line}\n",
        )
        invalid_review = {
            "slug": "brad-barclay", "field": "position:infor:date", "type": "position_date",
            "existing_line": existing_line, "incoming_line": incoming_line,
            "other_hash": source_hash("2019-05"),
        }
        second_invalid_review = {
            **invalid_review,
            "existing_line": "- Development Team Lead, [[Infor]], [[Victoria]], 2020-11 to 2022-02",
            "incoming_line": "- Software Development Manager, [[Infor]], [[Victoria]], 2022-02 to 2026-04",
            "other_hash": source_hash("2022-02"),
        }
        unrelated_review = {**invalid_review, "slug": "someone-else"}
        contact_review = {"slug": "brad-barclay", "field": "email", "other_hash": source_hash("email")}
        self.state_root.mkdir()
        (self.state_root / "pending_review.json").write_text(
            json.dumps([invalid_review, second_invalid_review, unrelated_review, contact_review]), encoding="utf-8",
        )
        original_pending = (self.state_root / "pending_review.json").read_bytes()
        self.assertEqual(main([
            "-e", str(self.personal_root), "-i", str(self.other_root),
            "-t", str(self.state_root), "-p", "brad-barclay", "-m", "-n",
        ]), 0)
        self.assertEqual((self.state_root / "pending_review.json").read_bytes(), original_pending)
        with patch("tools.merge_person_files.review_pending", return_value=0):
            self.assertEqual(main([
                "-e", str(self.personal_root), "-i", str(self.other_root),
                "-t", str(self.state_root), "-p", "brad-barclay", "-m",
            ]), 0)
        pending = json.loads((self.state_root / "pending_review.json").read_text(encoding="utf-8"))
        self.assertEqual(pending[:2], [unrelated_review, contact_review])
        self.assertEqual(len(pending), 2)
        self.assertIn(existing_line, personal_path.read_text(encoding="utf-8"))
        self.assertIn(incoming_line, personal_path.read_text(encoding="utf-8"))

    def test_sync_opens_interactive_review_for_changed_email(self):
        self.write_person(
            self.personal_root,
            "mark-li",
            "---\ntags: [person]\nslug: mark-li\nfirst_name: Mark\nlast_name: Li\nemail: old@example.com\n---\n",
        )
        self.write_person(
            self.other_root,
            "mark-li",
            "---\ntags: [person]\nslug: mark-li\nfirst_name: Mark\nlast_name: Li\nemail: new@example.com\n---\n",
        )

        with patch("tools.merge_person_files.review_pending", return_value=0) as review_pending:
            self.assertEqual(main([
                "--existing", str(self.personal_root),
                "--incoming", str(self.other_root),
                "--state-dir", str(self.state_root),
                "--slug", "mark-li",
            ]), 0)

        review_pending.assert_called_once()

    def test_sync_opens_interactive_review_for_existing_pending_email(self):
        self.write_person(
            self.personal_root,
            "mark-li",
            "---\ntags: [person]\nslug: mark-li\nfirst_name: Mark\nlast_name: Li\nemail: new@example.com\n---\n",
        )
        self.write_person(
            self.other_root,
            "mark-li",
            "---\ntags: [person]\nslug: mark-li\nfirst_name: Mark\nlast_name: Li\nemail: new@example.com\n---\n",
        )
        pending = [{"slug": "mark-li", "name": "Mark Li", "field": "email", "personal": "old@example.com", "other": "new@example.com", "other_hash": source_hash("new@example.com"), "type": "contact_info", "path": ""}]
        self.state_root.mkdir(exist_ok=True)
        (self.state_root / "pending_review.json").write_text(json.dumps(pending), encoding="utf-8")

        with patch("tools.merge_person_files.review_pending", return_value=0) as review_pending:
            self.assertEqual(main([
                "--existing", str(self.personal_root),
                "--incoming", str(self.other_root),
                "--state-dir", str(self.state_root),
                "--slug", "mark-li",
            ]), 0)

        review_pending.assert_called_once_with(unittest.mock.ANY, {"mark-li"})

    def test_review_can_apply_the_suggested_position_line(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [[Acme]], 2002-03 to 2003-10\n",
        )
        pending = [{
            "slug": "jane-doe", "name": "Jane Doe", "path": str(personal_path),
            "field": "position:acme:date", "type": "position_date",
            "existing_line": "- Engineer, [[Acme]], 2002-03 to 2003-10",
            "incoming_line": "- Engineer, [[Acme]], 2002-04 to 2003-11",
            "suggested_line": "- Engineer, [[Acme]], 2002-04 to 2003-10",
            "other_hash": source_hash("2002-04"),
        }]
        self.state_root.mkdir(exist_ok=True)
        (self.state_root / "pending_review.json").write_text(json.dumps(pending), encoding="utf-8")

        with patch("tools.merge_person_files.read_review_command", return_value="s"):
            self.assertEqual(review_pending(self.arguments()), 0)

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("- Engineer, [[Acme]], 2002-04 to 2003-10", updated)
        self.assertNotIn("2002-03 to 2003-10", updated)
        self.assertEqual(json.loads((self.state_root / "pending_review.json").read_text(encoding="utf-8")), [])

    def test_merge_adds_linkedin_profile_to_references_once(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## References\n\n- Personal site\n\n## Notes\n\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\nlinkedin_id: jane-doe-123\n---\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )
        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        reference = "[LinkedIn](https://www.linkedin.com/in/jane-doe-123)"
        self.assertIn(reference, updated)
        self.assertEqual(updated.count(reference), 1)

    def test_merge_removes_empty_reference_and_position_placeholders(self):
        reference = "[LinkedIn](https://www.linkedin.com/in/brad-barclay-b55218b8)"
        position = "- Bachelor of Science, Computational Science, [Brock University](Brock University), 1995 to 1999"
        for index, references in enumerate(("1.\n", "1. \n", f"1. \n2. {reference}\n")):
            with self.subTest(references=references):
                person_path = self.write_person(
                    self.personal_root, f"personal-{index}",
                    "---\ntags: [person]\nslug: brad-barclay\n---\n"
                    f"## References\n\n{references}\n## Positions\n\n- \n{position}\n"
                    "\n## Notes\n\n- \n",
                )
                other_path = self.write_person(
                    self.other_root, f"incoming-{index}",
                    "---\ntags: [person]\nslug: brad-barclay\nlinkedin_id: brad-barclay-b55218b8\n---\n"
                    f"## Positions\n\n- \n{position}\n",
                )
                synchronizer = PersonSynchronizer(self.arguments())
                synchronizer.merge_pair(read_document(person_path), read_document(other_path))
                updated = person_path.read_text(encoding="utf-8")
                self.assertIn(f"## References\n\n1. {reference}\n\n## Positions", updated)
                self.assertIn(f"## Positions\n\n{position.replace('[Brock University](Brock University)', '[[Brock University]]')}\n\n## Notes", updated)
                self.assertEqual(updated.count(reference), 1)
                self.assertTrue(updated.endswith("## Notes\n\n"))
                synchronizer.merge_pair(read_document(person_path), read_document(other_path))
                self.assertEqual(person_path.read_text(encoding="utf-8"), updated)

    def test_position_normalization_removes_only_empty_placeholder_blocks(self):
        self.assertEqual(render_position_blocks(["- \n", "* \n", "-\n", "*\n"], "\n"), "")
        self.assertEqual(
            render_position_blocks(["- \n\n  > Keep this description.\n"], "\n"),
            "-\n\n  > Keep this description.\n\n",
        )
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n\n-\n* \n"
            "- Engineer, [[Acme]], 2024-01\n-\n\n## Notes\n\n- \n",
        )
        PersonSynchronizer(self.arguments()).normalize_positions([read_document(person_path)])
        self.assertIn(
            "## Positions\n\n- Engineer, [[Acme]], 2024-01\n\n## Notes\n\n- \n",
            person_path.read_text(encoding="utf-8"),
        )

    def test_position_descriptions_exclude_standalone_research_skills(self):
        for description in (
            "Engineering REU, renewable energy",
            "Chemical Engineering REU, bioplastics and biocomposites",
        ):
            for label in ("> Research Skills", "  > research skills ", "  - Research Skills", "  > - Research Skills"):
                with self.subTest(description=description, label=label):
                    block = f"- Undergraduate Research Assistant, [[University]], 2016-06 to 2016-08\n\n> {description}\n>\n{label}\n"
                    normalized = normalize_position_description(block)
                    self.assertEqual(
                        normalized,
                        f"- Undergraduate Research Assistant, [[University]], 2016-06 to 2016-08\n\n  > {description}\n",
                    )
        self.assertIn(
            "Applied research skills to renewable energy.",
            normalize_position_description("- Assistant, [[University]], 2016\n> Applied research skills to renewable energy.\n"),
        )

    def test_created_person_excludes_research_skills_description_label(self):
        other_path = self.write_person(
            self.other_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n"
            "## Positions\n\n- Assistant, [[University]], 2016\n\n"
            "> Engineering REU, renewable energy\n>\n> Research Skills\n",
        )
        PersonSynchronizer(self.arguments()).create_person(read_document(other_path), set())
        created = (self.personal_root / "jane-doe" / "Jane Doe.md").read_text(encoding="utf-8")
        self.assertNotIn("Research Skills", created)
        self.assertIn("Engineering REU, renewable energy", created)

    def test_reference_placeholder_cleanup_preserves_real_entries_and_continuations(self):
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n"
            "## References\n\n1. \n2. [Website](https://example.com)\n"
            "   Keep this annotation.\n\n## Notes\n\n- Keep notes.\n",
        )
        other_path = self.write_person(
            self.other_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nlinkedin_id: jane-doe-123\n---\n",
        )
        PersonSynchronizer(self.arguments()).merge_pair(read_document(person_path), read_document(other_path))
        updated = person_path.read_text(encoding="utf-8")
        self.assertIn(
            "1. [Website](https://example.com)\n   Keep this annotation.\n\n"
            "2. [LinkedIn](https://www.linkedin.com/in/jane-doe-123)",
            updated,
        )
        self.assertIn("## Notes\n\n- Keep notes.\n", updated)

    def test_merge_preserves_existing_linkedin_reference_and_notes_content(self):
        link = "[LinkedIn](https://www.linkedin.com/in/brad-barclay-b55218b8)"
        notes = f"- {link}\n\nBrad Barclay OS2 Warp.png\n"
        person_path = self.write_person(
            self.personal_root, "brad-barclay",
            "---\ntags: [person]\nslug: brad-barclay\n---\n"
            f"## References\n\n1. {link}\n\n## Notes\n\n- \n{notes}",
        )
        other_path = self.write_person(
            self.other_root, "brad-barclay",
            "---\ntags: [person]\nslug: brad-barclay\nlinkedin_id: brad-barclay-b55218b8\n---\n",
        )
        PersonSynchronizer(self.arguments()).merge_pair(read_document(person_path), read_document(other_path))
        updated = person_path.read_text(encoding="utf-8")
        self.assertIn(f"## References\n\n1. {link}\n\n", updated)
        self.assertIn(f"## Notes\n\n{notes}", updated)
        self.assertEqual(updated.count(link), 2)

    def test_notes_cleanup_preserves_fenced_and_indented_content(self):
        notes = "\n- \n- Keep note.\n  - \n\n```\n- \n```\n\n~~~text\n- \n~~~\n"
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            f"---\ntags: [person]\nslug: jane-doe\n---\n## Notes\n{notes}",
        )
        PersonSynchronizer(self.arguments()).normalize_markdown_in_people([read_document(person_path)])
        self.assertTrue(person_path.read_text(encoding="utf-8").endswith(
            "## Notes\n" + notes.replace("\n- \n- Keep note.", "\n- Keep note.", 1),
        ))

    def test_merge_inserts_missing_references_in_template_order(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Bio\n\nA software engineer.\n\n## People\n\n- Colleague\n\n## Positions\n\n- Engineer, [[Acme]], 2024-01\n\n## Notes\n\n- Keep this note.\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\nlinkedin_id: jane-doe-123\n---\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertLess(updated.index("## Bio"), updated.index("## References"))
        self.assertLess(updated.index("## References"), updated.index("## People"))
        self.assertIn(
            "A software engineer.\n\n## References\n\n1. [LinkedIn](https://www.linkedin.com/in/jane-doe-123)\n\n## People",
            updated,
        )

    def test_merge_numbers_subsequent_linkedin_reference(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## References\n\n1. [Website](https://example.com)\n\n## Notes\n\n- Keep this note.\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\nlinkedin_id: jane-doe-123\n---\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("2. [LinkedIn](https://www.linkedin.com/in/jane-doe-123)", updated)

    def test_sync_repairs_mojibake_in_existing_and_incoming_content(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Notes\nSecrÃ©taire at Laurentienne G\u00e9n\u00e9rale\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Bio\nSecrÃ©taire\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertEqual(updated.count("Secrétaire"), 2)
        self.assertNotIn("SecrÃ©taire", updated)
        self.assertIn("Laurentienne Générale", updated)

    def test_normalize_positions_repairs_mojibake_without_incoming_files(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Notes\nSecrÃ©tariat\n",
        )

        self.assertEqual(main([
            "--existing", str(self.personal_root),
            "--normalize-positions",
            "--state-dir", str(self.state_root),
        ]), 0)

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("Secrétariat", updated)
        self.assertNotIn("SecrÃ©tariat", updated)

    def test_missing_skills_is_inserted_in_template_order(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nfirst_name: Jane\nlast_name: Doe\nprivate_field: preserve\n---\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nfirst_name: Jane\nlast_name: Doe\nskills:\n  - Python\n---\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertLess(updated.index("last_name: Doe"), updated.index("skills:"))
        self.assertLess(updated.index("skills:"), updated.index("private_field: preserve"))

    def test_merge_inserts_missing_bio_after_optional_photo(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n# Jane Doe\n\n![[media/jane-doe.jpg]]\n\n## Quotes\n\n> A quote.\n\n## Notes\n\n- Keep this note.\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n# Jane Doe\n\n## Bio\nA software engineer.\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertLess(updated.index("![[media/jane-doe.jpg]]"), updated.index("## Bio"))
        self.assertLess(updated.index("## Bio"), updated.index("## Quotes"))
        self.assertIn("## Bio\n\nA software engineer.\n\n## Quotes", updated)

    def test_position_uses_more_precise_non_conflicting_source_date(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [[Acme]], 2024-01 to 2024-05\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [[Acme]], 2024-01-15 to 2024-05-20\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        self.assertIn("2024-01-15 to 2024-05-20", personal_path.read_text(encoding="utf-8"))

    def test_closed_source_position_replaces_stale_current_position(self):
        personal_path = self.write_person(
            self.personal_root,
            "mark-leonard",
            "---\ntags: [person]\nslug: mark-leonard\nfirst_name: Mark\nlast_name: Leonard\n---\n## Positions\n- Vice President Development, [RDM](RDM), Waterloo, Ontario, 2014-09 #current\n",
        )
        self.write_person(
            self.other_root,
            "mark-leonard",
            "---\ntags: [person]\nslug: mark-leonard\nfirst_name: Mark\nlast_name: Leonard\n---\n## Positions\n- Vice President Development, [[RDM]], [[Waterloo]], 2014-09 to 2017-06\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("- Vice President Development, [[RDM]], [[Waterloo]], 2014-09 to 2017-06", updated)
        self.assertNotIn("#current", updated)

    def test_position_with_fenced_description_does_not_get_duplicate_source_description(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [Acme](Acme), 2024-01\n```\nOriginal description\n```\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [[Acme]], 2024-01\n\n  > Incoming description\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertNotIn("Original description", updated)
        self.assertIn("- Engineer, [[Acme]], 2024-01\n\n  > Incoming description", updated)

    def test_more_concise_incoming_position_description_replaces_existing_description(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [[Acme]], 2024-01\n\n  > Led several complex engineering projects, coordinated numerous teams, and delivered detailed technical solutions for customers.\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [[Acme]], 2024-01\n\n  > Delivered technical solutions.\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("- Engineer, [[Acme]], 2024-01\n\n  > Delivered technical solutions.", updated)
        self.assertNotIn("Led several complex engineering projects", updated)

    def test_incoming_position_description_replaces_existing_even_when_longer(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n"
            "- Engineer, [[Acme]], 2024-01\n\n  > Built systems.\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n"
            "- Engineer, [[Acme]], 2024-01\n\n  > Designed and delivered complex systems for customers.\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn(
            "- Engineer, [[Acme]], 2024-01\n\n  > Designed and delivered complex systems for customers.",
            updated,
        )
        self.assertNotIn("Built systems.", updated)

    def test_indented_position_description_with_date_is_not_a_position(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n"
            "- Coordinator, [[Guild]], 2017-10 to #current\n"
            "  > Campaign included committee service from 2018-19.\n"
            "- Member, [[Advisory Committee]], 2018-09 to #current\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n",
        )

        PersonSynchronizer(self.arguments()).normalize_positions(discover_people(self.personal_root))

        positions = personal_path.read_text(encoding="utf-8").split("## Positions\n", 1)[1]
        self.assertIn(
            "- Coordinator, [[Guild]], 2017-10 to #current\n\n"
            "  > Campaign included committee service from 2018-19.\n\n"
            "- Member, [[Advisory Committee]], 2018-09 to #current",
            positions,
        )
        self.assertEqual(positions.count("Campaign included committee service"), 1)
        self.assertEqual(positions.count("- Member, [[Advisory Committee]]"), 1)

    def test_merge_normalizes_legacy_descriptions_and_matches_unlinked_organization(self):
        registry_path = self.root / "organizations.json"
        registry_path.write_text(
            '[{"name": "CBC"}, {"name": "Canadian Media Guild"}]',
            encoding="utf-8",
        )
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n"
            "## Bio\n> Teacher and analyst in labour and media issues.\n"
            "## Positions\n"
            "- News Producer, [CBC](CBC), [[Toronto]], 1983-04 to 2019-06, Toronto\n"
            "  > Did a wide range of senior journalistic functions involving the production of daily news.\n"
            "  >\n"
            "  > During final few years I wrote, edited and produced news for CBC TV's News Network, with emphasis on breaking national and provincial politics.\n"
            "- National President, Canadian Media Guild, 2000 to 2010, Toronto\n"
            "\t- Led the Canadian Media Guild as CEO, managing a budget over $6M and a staff of 16, and developed strategy for bargaining.\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n"
            "## Bio\nA journalist and consultant.\n"
            "## Positions\n"
            "- News Producer, [[CBC]], [[Toronto]], 1983-04 to 2019-06\n"
            "  > Did a wide range of senior journalistic functions involving the production of daily news.\n"
            "  > During final few years I wrote, edited and produced news for CBC TV's News Network, with emphasis on breaking national and provincial politics.\n"
            "- National President, [[Canadian Media Guild]], [[Toronto]], 2000 to 2010\n"
            "  > Led the Canadian Media Guild as CEO and developed strategy for bargaining.\n",
        )
        args = self.arguments()
        args.organizations_config = str(registry_path)

        self.assertEqual(main([
            "--existing", str(self.personal_root),
            "--incoming", str(self.other_root),
            "--state-dir", str(self.state_root),
            "--organizations-config", str(registry_path),
            "--slug", "jane-doe",
            "--normalize-positions",
        ]), 0)

        updated = personal_path.read_text(encoding="utf-8")
        self.assertEqual(updated.count("News Producer,"), 1)
        self.assertEqual(updated.count("National President,"), 1)
        self.assertIn("- News Producer, [[CBC]], [[Toronto]], 1983-04 to 2019-06", updated)
        self.assertIn("- National President, [[Canadian Media Guild]], 2000 to 2010, Toronto", updated)
        self.assertIn(
            "  > Did a wide range of senior journalistic functions involving the production of daily news. "
            "During final few years I wrote, edited and produced news for CBC TV's News Network, with emphasis on "
            "breaking national and provincial politics.",
            updated,
        )
        self.assertIn(
            "  > Led the Canadian Media Guild as CEO and developed strategy for bargaining.",
            updated,
        )
        self.assertNotIn("\t- Led the Canadian Media Guild as CEO", updated)
        self.assertNotIn("[CBC](CBC)", updated)
        self.assertIn(
            "## Bio\n\n> Teacher and analyst in labour and media issues.\n>\n> A journalist and consultant.",
            updated,
        )

    def test_matched_position_uses_incoming_organization_wikilink(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [Acme](Acme), 2024-01\n\n  > Personal description\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [[Acme]], 2024-01\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("- Engineer, [[Acme]], 2024-01\n\n  > Personal description", updated)

    def test_position_matches_organization_with_accented_alias(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Information Officer, [[Elections Canada]], British Columbia, 2015-10 to 2015-10\n\n  > Original description\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Information Officer, [[Élections Canada | Elections Canada]], [[British Columbia]], 2015-10 #current\n\n  > Incoming description\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertEqual(updated.count("Information Officer"), 1)

    def test_position_matches_organization_registry_aliases(self):
        registry_path = self.root / "organizations.json"
        registry_path.write_text(
            '[{"name": "Wheelabrator", "aliases": ["Wheelabrator Group", "Wheelabrator Canada"]}]',
            encoding="utf-8",
        )
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Assistant Controller, [[Wheelabrator Group]], 1974-01 to 1980-01\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Assistant Controller, [[Wheelabrator Canada]], 1974-01 to 1980-01\n",
        )
        args = self.arguments()
        args.organizations_config = str(registry_path)

        PersonSynchronizer(args).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        self.assertEqual(personal_path.read_text(encoding="utf-8").count("Assistant Controller"), 1)

    def test_existing_equivalent_organization_alias_positions_are_deduplicated(self):
        registry_path = self.root / "organizations.json"
        registry_path.write_text(
            '[{"name": "Wheelabrator", "aliases": ["Wheelabrator Group", "Wheelabrator Canada"]}]',
            encoding="utf-8",
        )
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Assistant Controller, [Wheelabrator Group](Wheelabrator Group), 1974-01 to 1980-01\n- Assistant Controller, [Wheelabrator Canada](Wheelabrator Canada), 1974-01 to 1980-01\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n",
        )
        args = self.arguments()
        args.organizations_config = str(registry_path)

        PersonSynchronizer(args).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertEqual(updated.count("Assistant Controller"), 1)
        self.assertIn("[[Wheelabrator]]", updated)

    def test_company_only_position_is_replaced_by_same_start_dated_titled_position(self):
        registry_path = self.root / "organizations.json"
        registry_path.write_text("[]", encoding="utf-8")
        person_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n"
            "## Positions\n- [[Kindryl]], 2026-09 #current\n",
        )
        other_path = self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n"
            "## Positions\n- Vice President, [[Kyndryl]], 2026-09 #current\n",
        )
        args = self.arguments()
        args.organizations_config = str(registry_path)
        synchronizer = PersonSynchronizer(args)

        synchronizer.merge_pair(read_document(person_path), read_document(other_path))

        updated = person_path.read_text(encoding="utf-8")
        self.assertIn("- Vice President, [[Kyndryl]], 2026-09 #current", updated)
        self.assertNotIn("[[Kindryl]]", updated)
        self.assertEqual(updated.count("2026-09"), 1)
        synchronizer.merge_pair(read_document(person_path), read_document(other_path))
        self.assertEqual(person_path.read_text(encoding="utf-8"), updated)

    def test_overlapping_company_only_current_position_is_replaced_by_titled_position(self):
        person_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n"
            "## Positions\n- [[Hitron]], 2023-02 #current\n",
        )
        other_path = self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n"
            "## Positions\n- Product Innovation Manager, [[Hitron]], 2023-03 #current\n",
        )
        synchronizer = PersonSynchronizer(self.arguments())

        synchronizer.merge_pair(read_document(person_path), read_document(other_path))

        updated = person_path.read_text(encoding="utf-8")
        self.assertIn("- Product Innovation Manager, [[Hitron]], 2023-03 #current", updated)
        self.assertNotIn("- [[Hitron]], 2023-02 #current", updated)
        self.assertEqual(updated.count("[[Hitron]]"), 1)
        synchronizer.merge_pair(read_document(person_path), read_document(other_path))
        self.assertEqual(person_path.read_text(encoding="utf-8"), updated)

    def test_undated_equivalent_education_positions_are_merged(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- B.Sc - Economics, [Swansea University](Swansea University)\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- B.Sc, Economics, [University of Wales](University of Wales), Swansea, Wales\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        self.assertEqual(personal_path.read_text(encoding="utf-8").count("B.Sc"), 1)

    def test_plain_and_split_link_education_entries_are_merged_and_deduplicated(self):
        plain = "- Master of Business Administration, Finance, SVKM's Narsee Monjee Institute of Management Studies (NMIMS)"
        linked = "- Master of Business Administration, Finance, [SVKM](SVKM), [Narsee Monjee Institute of Management Studies](Narsee Monjee Institute of Management Studies)"
        for index, personal_positions in enumerate((plain, f"{plain}\n{linked}")):
            with self.subTest(personal_positions=personal_positions):
                person_path = self.write_person(
                    self.personal_root, f"person-{index}",
                    f"---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n{personal_positions}\n",
                )
                other_path = self.write_person(
                    self.other_root, f"person-{index}",
                    f"---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n{linked}\n\n  > Finance studies.\n",
                )
                synchronizer = PersonSynchronizer(self.arguments())
                synchronizer.merge_pair(read_document(person_path), read_document(other_path))
                updated = person_path.read_text(encoding="utf-8")
                self.assertEqual(updated.count("Master of Business Administration"), 1)
                self.assertIn("Finance studies.", updated)
                synchronizer.normalize_positions([read_document(person_path)])
                self.assertEqual(person_path.read_text(encoding="utf-8").count("Master of Business Administration"), 1)

    def test_split_link_education_does_not_match_different_institution(self):
        plain = "- Master of Business Administration, Finance, Other Institute of Management Studies"
        linked = "- Master of Business Administration, Finance, [SVKM](SVKM), [Narsee Monjee Institute of Management Studies](Narsee Monjee Institute of Management Studies)"
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            f"---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n{plain}\n",
        )
        other_path = self.write_person(
            self.other_root, "jane-doe",
            f"---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n{linked}\n",
        )
        PersonSynchronizer(self.arguments()).merge_pair(read_document(person_path), read_document(other_path))
        self.assertEqual(person_path.read_text(encoding="utf-8").count("Master of Business Administration"), 2)

    def test_normalization_deduplicates_plain_and_split_link_mba_entries(self):
        person_path = self.write_person(
            self.personal_root, "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\n---\n## Positions\n"
            "- Master of Business Administration, Finance, SVKM's Narsee Monjee Institute of Management Studies (NMIMS)\n"
            "- Master of Business Administration, Finance, [SVKM](SVKM), [Narsee Monjee Institute of Management Studies](Narsee Monjee Institute of Management Studies)\n",
        )
        synchronizer = PersonSynchronizer(self.arguments())
        synchronizer.normalize_positions([read_document(person_path)])
        updated = person_path.read_text(encoding="utf-8")
        self.assertEqual(updated.count("Master of Business Administration"), 1)
        self.assertIn("Narsee Monjee Institute of Management Studies", updated)
        synchronizer.normalize_positions([read_document(person_path)])
        self.assertEqual(person_path.read_text(encoding="utf-8"), updated)

    def test_deduplicates_concise_and_detailed_bachelor_entries_at_same_university(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- BSc, Mathematics, [[University of Toronto]]\n- Honour's B.Sc. Biophysics specialist, Mathematics major, [[University of Toronto]], 1997\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertNotIn("- BSc, Mathematics, [[University of Toronto]]", updated)
        self.assertEqual(updated.count("University of Toronto"), 1)
        self.assertIn("Honour's B.Sc. Biophysics specialist, Mathematics major, [[University of Toronto]], 1997", updated)

    def test_dated_and_undated_equivalent_education_positions_are_merged(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- BASc - Engineering Science -- Computer Engineering, [University of Toronto](University of Toronto)\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- BASc, Engineering Science -- Computer Engineering, [University of Toronto](University of Toronto), 1985 to 1988\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertEqual(updated.count("BASc"), 1)
        self.assertIn("1985 to 1988", updated)

    def test_dated_bs_education_replaces_undated_equivalent(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- BS, Public Relations, [University of Florida](University of Florida)\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- BS, Public Relations, [University of Florida](University of Florida), 1988 to 1993\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertEqual(updated.count("BS, Public Relations"), 1)
        self.assertIn("1988 to 1993", updated)

    def test_dated_and_undated_education_with_shared_degree_are_merged(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- PhD, Electrical/Computer Engineering, [University of Toronto](University of Toronto), 1981 to 1991\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- PhD, MEng, Computer/Electrical Engineering, [University of Toronto](University of Toronto)\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = personal_path.read_text(encoding="utf-8")
        self.assertEqual(updated.count("University of Toronto"), 1)
        self.assertIn("1981 to 1991", updated)

    def test_identical_undated_positions_are_not_appended_from_incoming(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Independent consultant, [[Acme]]\n",
        )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Independent consultant, [[Acme]]\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        self.assertEqual(personal_path.read_text(encoding="utf-8").count("Independent consultant"), 1)

    def test_other_only_person_is_created_in_folder_per_person_layout(self):
        self.write_person(
            self.other_root,
            "source-folder",
            "---\ntags: [person]\nslug: source-slug\nfirst_name: Jane\nlast_name: Doe\n---\n## Bio\nNew person\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        self.assertTrue((self.personal_root / "jane-doe" / "Jane Doe.md").exists())
        self.assertFalse((self.personal_root / "jane-doe" / "media").exists())

    def test_other_only_person_omits_empty_deprecated_sections(self):
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n# Jane Doe\n\n## Interests\n\n## Communications\n\n## Notes\nKeep this note.\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = (self.personal_root / "jane-doe" / "Jane Doe.md").read_text(encoding="utf-8")
        self.assertNotIn("## Interests", updated)
        self.assertNotIn("## Communications", updated)
        self.assertIn("## Notes\n\nKeep this note.\n", updated)

    def test_other_only_person_retains_populated_deprecated_sections(self):
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n# Jane Doe\n\n## Interests\n- Reading\n\n## Communications\n\n## Notes\nKeep this note.\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = (self.personal_root / "jane-doe" / "Jane Doe.md").read_text(encoding="utf-8")
        self.assertIn("## Interests\n\n- Reading\n", updated)
        self.assertNotIn("## Communications", updated)

    def test_other_only_person_removes_invalid_single_character_place_link(self):
        self.write_person(
            self.other_root,
            "lisa-hotchkiss",
            "---\ntags: [person]\nslug: lisa-hotchkiss\nfirst_name: Lisa\nlast_name: Hotchkiss\n---\n## Positions\n- Marketing Communications Manager, [[Nortel]], [[• Developed collateral]], 2007-01 to 2009-12\n",
        )

        PersonSynchronizer(self.arguments()).match_and_sync(
            discover_people(self.personal_root), discover_people(self.other_root)
        )

        updated = (self.personal_root / "lisa-hotchkiss" / "Lisa Hotchkiss.md").read_text(encoding="utf-8")
        self.assertIn("Marketing Communications Manager, [[Nortel]], 2007-01 to 2009-12", updated)
        self.assertNotIn("[[• Developed collateral]]", updated)

    def test_conflicted_existing_slug_is_never_overwritten_or_created(self):
        for folder in ("jane-doe", "jane-doe-original"):
            self.write_person(
                self.personal_root,
                folder,
                "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Notes\nKeep\n",
            )
        self.write_person(
            self.other_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Bio\nIncoming\n",
        )
        synchronizer = PersonSynchronizer(self.arguments())

        synchronizer.match_and_sync([], discover_people(self.other_root), {"jane-doe"})

        self.assertEqual(synchronizer.matches[0]["status"], "skipped_slug_conflict")
        self.assertIn("## Notes\nKeep\n", (self.personal_root / "jane-doe" / "Jane Doe.md").read_text(encoding="utf-8"))

    def test_discovery_skips_note_with_empty_tags_without_crashing(self):
        note_folder = self.personal_root / "lisa"
        note_folder.mkdir()
        (note_folder / "Meditation.md").write_text("---\ntags:\n---\n# Meditation\n", encoding="utf-8")

        self.assertEqual(discover_people(self.personal_root), [])

    def test_persisted_decision_is_reused_when_source_value_is_unchanged(self):
        store = SyncStore(self.state_root, False)
        store.decisions["jane-doe:mobile"] = {"decision": "kept_personal", "other_hash": source_hash("555-0200")}
        self.assertEqual(store.decision("jane-doe", "mobile", "555-0200"), "kept_personal")
        self.assertIsNone(store.decision("jane-doe", "mobile", "555-0300"))

    def test_dry_run_writes_a_proposed_changes_report(self):
        PersonSynchronizer(self.arguments(dry_run=True)).write_reports([])
        PersonSynchronizer(self.arguments()).write_reports([])

        self.assertTrue((self.state_root / "changes_proposed.csv").exists())
        self.assertTrue((self.state_root / "changes_applied.csv").exists())

    def test_applied_changes_report_appends_timestamped_rows(self):
        person_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n",
        )
        person = discover_people(self.personal_root)[0]
        first = PersonSynchronizer(self.arguments())
        first.record_change(person, "skills", [], ["Python"])
        first.write_reports([])
        second = PersonSynchronizer(self.arguments())
        second.record_change(person, "Bio", "", "A software engineer.")
        second.write_reports([])

        with (self.state_root / "changes_applied.csv").open(newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["field"] for row in rows], ["skills", "Bio"])
        self.assertTrue(all(row["date"] and row["time"] for row in rows))

    def test_reconnect_report_flags_recent_position_without_interaction(self):
        recent_date = (dt.date.today() - dt.timedelta(days=7)).isoformat()
        self.write_person(
            self.personal_root,
            "jane-doe",
            f"---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Engineer, [[Acme]], {recent_date}\n\n## Notes\n- Older note\n",
        )
        rows = PersonSynchronizer(self.arguments()).reconnect_rows(discover_people(self.personal_root))

        self.assertEqual(rows[0]["slug"], "jane-doe")
        self.assertEqual(rows[0]["change_type"], "job")


if __name__ == "__main__":
    unittest.main()