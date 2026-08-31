import datetime as dt
import csv
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from sync_person_files import (
    PersonSynchronizer, SyncStore, default_config_dir, default_dev_output_dir,
    discover_people, main, source_hash,
)
from text_encoding import repair_mojibake


class SyncPersonFilesTests(unittest.TestCase):
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
        self.assertEqual(default_config_dir("posix", {}), Path("/mnt/c/data/dev-output/config"))
        self.assertEqual(default_config_dir("posix", {"HAL_MD_CONFIG_DIR": "/data/config"}), Path("/data/config"))

    def test_repair_mojibake_is_available_as_shared_utility(self):
        self.assertEqual(repair_mojibake("SecrÃ©tariat"), "Secrétariat")
        self.assertEqual(repair_mojibake("Laurentienne Générale"), "Laurentienne Générale")

    def arguments(self, dry_run=False):
        return Namespace(
            existing=str(self.personal_root), state_dir=str(self.state_root), dry_run=dry_run,
            bio_similarity=0.70, auto_match_threshold=0.96, review_match_threshold=0.80,
            lookback_days=365,
        )

    def write_person(self, root, folder, content):
        path = root / folder
        path.mkdir()
        file_path = path / "Jane Doe.md"
        file_path.write_text(content, encoding="utf-8")
        return file_path

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
        self.assertIn("## Notes\nDo not rewrite this section.\n", updated)
        self.assertIn("## Bio\n\nA software engineer!\n", updated)
        skills_change = next(change for change in synchronizer.changes if change["field"] == "skills")
        self.assertEqual(skills_change["old_value"], '["Python"]')
        self.assertEqual(skills_change["new_value"], '["Python", "Rust"]')

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
        self.assertIn("## Notes\n- A code sample\n\n  ```\n  remain unchanged\n  ```\n", updated)

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

    def test_normalize_positions_orders_entries_chronologically(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Manager, [[Acme]], 2024-01\n- Engineer, [[Acme]], 2023-01\n",
        )

        PersonSynchronizer(self.arguments()).normalize_positions(discover_people(self.personal_root))

        updated = personal_path.read_text(encoding="utf-8")
        self.assertLess(updated.index("Engineer, [[Acme]], 2023-01"), updated.index("Manager, [[Acme]], 2024-01"))

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

        with patch("sync_person_files.review_pending", return_value=0) as review_pending:
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

        with patch("sync_person_files.review_pending", return_value=0) as review_pending:
            self.assertEqual(main([
                "--existing", str(self.personal_root),
                "--incoming", str(self.other_root),
                "--state-dir", str(self.state_root),
                "--slug", "mark-li",
            ]), 0)

        review_pending.assert_called_once_with(unittest.mock.ANY, {"mark-li"})

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
        self.assertIn("Original description", updated)
        self.assertNotIn("Incoming description", updated)

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