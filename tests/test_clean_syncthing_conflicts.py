import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools.clean_syncthing_conflicts import (
    CHUNK_SIZE,
    clean_conflicts,
    main,
    original_path,
    same_contents,
)


class CleanSyncthingConflictsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = io.StringIO()
        self.errors = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.enterContext(redirect_stderr(self.errors))

    def conflict(self, name="photo.jpg", index=1, content=b"photo", folder=None):
        target = (folder or self.root) / name
        path = target.with_name(
            f"{target.stem}.sync-conflict-20261107-22175{index}-QRX7PZB{target.suffix}"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_original_names(self):
        for name in ("photo.jpg", "archive.tar.gz", "README", ".env", "a.b.c"):
            with self.subTest(name=name):
                conflict = self.conflict(name)
                self.assertEqual(original_path(conflict), self.root / name)
        for name in ("photo.jpg", "a.sync-conflict-bogus.jpg", "a.sync-conflict-20261107-221752-.jpg"):
            self.assertIsNone(original_path(self.root / name))

    def test_missing_original_restores_one_and_removes_identical_conflicts(self):
        first = self.conflict(index=1)
        second = self.conflict(index=2)
        os.utime(first, (1_600_000_000, 1_600_000_000))
        mtime = first.stat().st_mtime_ns
        result = clean_conflicts([self.root], apply=True)
        target = self.root / "photo.jpg"
        self.assertEqual(target.read_bytes(), b"photo")
        self.assertEqual(target.stat().st_mtime_ns, mtime)
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        self.assertEqual((result.restored, result.removed, result.errors), (1, 1, 0))

    def test_single_conflict_restores_original(self):
        conflict = self.conflict()
        result = clean_conflicts([self.root], apply=True)
        self.assertEqual((self.root / "photo.jpg").read_bytes(), b"photo")
        self.assertFalse(conflict.exists())
        self.assertEqual((result.restored, result.removed), (1, 0))

    def test_existing_original_removes_only_identical_conflicts(self):
        target = self.root / "photo.jpg"
        target.write_bytes(b"photo")
        before = target.stat()
        paths = [self.conflict(index=index) for index in (1, 2)]
        result = clean_conflicts([self.root], apply=True)
        self.assertEqual(target.stat().st_ino, before.st_ino)
        self.assertEqual(target.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertEqual((result.restored, result.removed), (0, 2))

    def test_differing_contents_leave_entire_group_untouched(self):
        for original, other in ((None, b"other"), (b"photo", b"other"), (b"photo", b"longer")):
            with self.subTest(original=original, other=other):
                target = self.root / "photo.jpg"
                if original is not None:
                    target.write_bytes(original)
                paths = [self.conflict(index=1), self.conflict(index=2, content=other)]
                result = clean_conflicts([self.root], apply=True)
                self.assertEqual(result.unresolved, 1)
                self.assertEqual((result.restored, result.removed), (0, 0))
                self.assertEqual(paths[0].read_bytes(), b"photo")
                self.assertEqual(paths[1].read_bytes(), other)
                self.assertEqual(target.exists(), original is not None)

    def test_dry_run_is_default_and_does_not_change_any_files(self):
        first = self.conflict()
        second = self.conflict(index=2)
        before = {p: p.read_bytes() for p in self.root.iterdir()}
        self.assertEqual(main([str(self.root)]), 0)
        self.assertEqual({p: p.read_bytes() for p in self.root.iterdir()}, before)
        self.assertIn("WOULD RESTORE", self.output.getvalue())
        self.assertIn("WOULD REMOVE", self.output.getvalue())
        self.assertTrue(first.exists() and second.exists())

    def test_existing_original_dry_run(self):
        target = self.root / "photo.jpg"
        target.write_bytes(b"photo")
        conflict = self.conflict()
        self.assertEqual(main([str(self.root), "--dry-run"]), 0)
        self.assertTrue(conflict.exists())
        self.assertIn("Would restore 0, remove 1", self.output.getvalue())

    def test_recursive_multiple_and_overlapping_roots(self):
        nested = self.root / "a" / "nested"
        other = self.root / "b"
        self.conflict(folder=nested)
        self.conflict(folder=other)
        result = clean_conflicts([self.root, nested, self.root], apply=True)
        self.assertEqual(result.restored, 2)
        self.assertTrue((nested / "photo.jpg").exists())
        self.assertTrue((other / "photo.jpg").exists())

    def test_different_original_names_are_not_deduplicated(self):
        self.conflict("20221115_113747.jpg")
        self.conflict("20230708_075208.jpg")
        result = clean_conflicts([self.root], apply=True)
        self.assertEqual((result.restored, result.removed), (2, 0))
        self.assertTrue((self.root / "20221115_113747.jpg").exists())
        self.assertTrue((self.root / "20230708_075208.jpg").exists())

    def test_empty_files_are_byte_identical(self):
        self.conflict(content=b"")
        self.conflict(index=2, content=b"")
        result = clean_conflicts([self.root], apply=True)
        self.assertEqual((result.restored, result.removed), (1, 1))
        self.assertEqual((self.root / "photo.jpg").read_bytes(), b"")

    def test_comparison_checks_bytes_beyond_first_chunk(self):
        first = self.conflict(content=b"x" * CHUNK_SIZE + b"a")
        second = self.conflict(index=2, content=b"x" * CHUNK_SIZE + b"b")
        self.assertFalse(same_contents(first, second))

    def test_invalid_root_prevents_all_changes(self):
        conflict = self.conflict()
        self.assertEqual(main([str(self.root), str(self.root / "missing"), "--apply"]), 1)
        self.assertTrue(conflict.exists())
        self.assertIn("ERROR", self.errors.getvalue())

    def test_target_directory_is_not_overwritten(self):
        (self.root / "photo.jpg").mkdir()
        conflict = self.conflict()
        result = clean_conflicts([self.root], apply=True)
        self.assertEqual(result.errors, 1)
        self.assertTrue(conflict.exists())
        self.assertTrue((self.root / "photo.jpg").is_dir())

    def test_existing_target_symlink_is_not_followed(self):
        destination = self.root / "destination"
        destination.write_bytes(b"photo")
        try:
            (self.root / "photo.jpg").symlink_to(destination)
        except OSError as error:
            self.skipTest(f"Symlinks unavailable: {error}")
        conflict = self.conflict()
        result = clean_conflicts([self.root], apply=True)
        self.assertEqual(result.errors, 1)
        self.assertTrue(conflict.exists())
        self.assertEqual(destination.read_bytes(), b"photo")

    def test_conflict_symlink_is_rejected_without_following_it(self):
        conflict = self.conflict()
        lstat = Path.lstat

        def symlink_stat(path, *args, **kwargs):
            if path == conflict:
                info = lstat(path, *args, **kwargs)
                return os.stat_result((stat.S_IFLNK, *tuple(info)[1:]))
            return lstat(path, *args, **kwargs)

        with patch.object(Path, "lstat", symlink_stat):
            result = clean_conflicts([self.root], apply=True)
        self.assertEqual(result.errors, 1)
        self.assertTrue(conflict.exists())
        self.assertFalse((self.root / "photo.jpg").exists())

    def test_unsupported_hard_links_preserve_conflict_and_report_failure(self):
        conflict = self.conflict()
        with patch("tools.clean_syncthing_conflicts.os.link", side_effect=OSError("not supported")):
            self.assertEqual(main([str(self.root), "--apply"]), 1)
        self.assertEqual(conflict.read_bytes(), b"photo")
        self.assertFalse((self.root / "photo.jpg").exists())
        self.assertIn("not supported", self.errors.getvalue())

    def test_restore_never_overwrites_target_that_appears_after_comparison(self):
        conflict = self.conflict()
        target = self.root / "photo.jpg"
        link = os.link

        def create_target_then_link(source, destination, **kwargs):
            target.write_bytes(b"new data")
            return link(source, destination, **kwargs)

        with patch("tools.clean_syncthing_conflicts.os.link", side_effect=create_target_then_link):
            result = clean_conflicts([self.root], apply=True)
        self.assertEqual(result.errors, 1)
        self.assertEqual(target.read_bytes(), b"new data")
        self.assertEqual(conflict.read_bytes(), b"photo")

    def test_delete_errors_are_reported_and_return_failure(self):
        (self.root / "photo.jpg").write_bytes(b"photo")
        conflict = self.conflict()
        with patch.object(Path, "unlink", side_effect=PermissionError("blocked")):
            self.assertEqual(main([str(self.root), "--apply"]), 1)
        self.assertTrue(conflict.exists())
        self.assertIn("blocked", self.errors.getvalue())

    def test_scan_errors_are_reported(self):
        with patch("tools.clean_syncthing_conflicts.os.walk", side_effect=PermissionError("scan blocked")):
            self.assertEqual(main([str(self.root), "--apply"]), 1)
        self.assertIn("scan blocked", self.errors.getvalue())

    def test_changed_contents_are_rechecked_before_deletion(self):
        (self.root / "photo.jpg").write_bytes(b"photo")
        conflict = self.conflict()
        compare = same_contents
        calls = 0

        def change_before_second_compare(first, second):
            nonlocal calls
            calls += 1
            if calls == 2:
                conflict.write_bytes(b"other")
            return compare(first, second)

        with patch("tools.clean_syncthing_conflicts.same_contents", side_effect=change_before_second_compare):
            result = clean_conflicts([self.root], apply=True)
        self.assertEqual(result.errors, 1)
        self.assertEqual(conflict.read_bytes(), b"other")


if __name__ == "__main__":
    unittest.main()
