import datetime as dt
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from sync_person_files import PersonSynchronizer, SyncStore, discover_people, main, source_hash


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

    def test_normalize_positions_converts_only_fenced_description(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n* Engineer, [[Acme]], 2023-01-02\n\n    ```\n    Built systems\n    Led projects\n    ```\n\n- Manager, [[Acme]], 2024-01-02\n```\nManaged teams\n```\n\n## Notes\n- A code sample\n\n  ```\n  remain unchanged\n  ```\n",
        )
        synchronizer = PersonSynchronizer(self.arguments())

        synchronizer.normalize_positions(discover_people(self.personal_root))

        updated = personal_path.read_text(encoding="utf-8")
        self.assertIn("  > - Built systems\n  > - Led projects\n", updated)
        self.assertIn("  > - Managed teams\n", updated)
        self.assertNotIn("```", updated.split("## Notes", 1)[0])
        self.assertIn("## Notes\n- A code sample\n\n  ```\n  remain unchanged\n  ```\n", updated)

    def test_normalize_positions_orders_entries_chronologically(self):
        personal_path = self.write_person(
            self.personal_root,
            "jane-doe",
            "---\ntags: [person]\nslug: jane-doe\nfirst_name: Jane\nlast_name: Doe\n---\n## Positions\n- Manager, [[Acme]], 2024-01\n- Engineer, [[Acme]], 2023-01\n",
        )

        PersonSynchronizer(self.arguments()).normalize_positions(discover_people(self.personal_root))

        updated = personal_path.read_text(encoding="utf-8")
        self.assertLess(updated.index("Engineer, [[Acme]], 2023-01"), updated.index("Manager, [[Acme]], 2024-01"))

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
        self.assertIn("first_name: Jane\n---\n", updated)

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