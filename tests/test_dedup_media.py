import io
import os
import tempfile
import unittest
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from tools.dedup_media import (
    MarkdownReferenceIndex,
    MediaFile,
    build_media_index,
    build_markdown_reference_index,
    detect_mime_type,
    describe_group,
    file_url,
    format_file_dates,
    handle_empty_files,
    main,
    parse_arguments,
    process_groups,
    relocate_media_file,
)


class DedupMediaTests(unittest.TestCase):
    def test_all_folders_is_opt_in(self):
        with patch("sys.argv", ["dedup_media.py"]):
            self.assertFalse(parse_arguments().all_folders)
        with patch("sys.argv", ["dedup_media.py", "--all-folders"]):
            self.assertTrue(parse_arguments().all_folders)

    def test_all_folders_scans_root_and_nested_files_and_excludes_output_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [
                root / "photo.jpg",
                root / "Photos" / "nested" / "copy.jpg",
                root / "person" / "media" / "copy.jpg",
                root / ".hidden.jpg",
                root / "media_dedup_index.json",
            ]
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"same image")

            default_files, default_groups = build_media_index(root)
            self.assertEqual([file.path for file in default_files], [paths[2]])
            self.assertEqual(default_groups, [])

            all_files, all_groups = build_media_index(
                root, all_folders=True, excluded_paths={paths[4].resolve()}
            )
            self.assertEqual({file.path for file in all_files}, set(paths[:3]))
            self.assertEqual(len(all_groups), 1)
            self.assertEqual(len(all_groups[0]), 3)

            cached = {file.relative_path: file for file in all_files}
            with patch("tools.dedup_media.sha256_file", side_effect=AssertionError("rehash")):
                _, cached_groups = build_media_index(root, cached, True, {paths[4].resolve()})
            self.assertEqual(cached_groups, all_groups)
            narrowed_files, _ = build_media_index(root, cached)
            self.assertEqual([file.path for file in narrowed_files], [paths[2]])

    def test_main_all_folders_keeps_chosen_copy_without_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / str(index) / "photo.jpg" for index in range(5)]
            for index, path in enumerate(paths):
                path.parent.mkdir()
                path.write_bytes(b"same image")
                os.utime(path, (1_600_000_000 + index, 1_600_000_000 + index))
            kept_stat = paths[2].stat()
            arguments = [
                "dedup_media.py", "-f", str(root), "--all-folders",
                "-o", str(root / "output"),
            ]

            with patch("sys.argv", arguments), patch(
                "tools.dedup_media.prompt", return_value="3"
            ):
                self.assertEqual(main(), 0)

            self.assertTrue(paths[2].is_file())
            self.assertTrue(all(not path.exists() for path in paths if path != paths[2]))
            self.assertEqual(paths[2].stat().st_mtime_ns, kept_stat.st_mtime_ns)
            if hasattr(kept_stat, "st_birthtime"):
                self.assertEqual(paths[2].stat().st_birthtime, kept_stat.st_birthtime)
            self.assertTrue((root / "output" / "media_dedup_index.json").is_file())

    def test_main_all_folders_wires_cached_update_and_regeneration(self):
        for choice in ("u", "r"):
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                first = root / "first.jpg"
                second = root / "Photos" / "second.jpg"
                second.parent.mkdir()
                first.write_bytes(b"same image")
                second.write_bytes(b"same image")
                arguments = [
                    "dedup_media.py", "-f", str(root), "--all-folders", "-o", str(root)
                ]
                with patch("sys.argv", arguments), patch(
                    "tools.dedup_media.prompt", return_value="s"
                ):
                    self.assertEqual(main(), 0)
                with patch("sys.argv", arguments), patch(
                    "tools.dedup_media.prompt", side_effect=[choice, "2"]
                ):
                    self.assertEqual(main(), 0)
                self.assertFalse(first.exists())
                self.assertTrue(second.is_file())
                self.assertTrue((root / "media_dedup_index.json").is_file())

    def test_file_dates_use_birth_time_and_timezone_offset(self):
        stat_result = Mock(st_birthtime=1_500_000_000, st_mtime=1_600_000_000)
        created = datetime.fromtimestamp(stat_result.st_birthtime).astimezone().isoformat(
            sep=" ", timespec="seconds"
        )
        modified = datetime.fromtimestamp(stat_result.st_mtime).astimezone().isoformat(
            sep=" ", timespec="seconds"
        )
        self.assertEqual(
            format_file_dates(stat_result),
            f"Created: {created}; Last modified: {modified}",
        )

    def test_file_dates_do_not_use_unix_change_time_as_creation_time(self):
        stat_result = Mock(spec=["st_ctime", "st_mtime"], st_ctime=1, st_mtime=1_600_000_000)
        with patch("tools.dedup_media.os.name", "posix"):
            self.assertIn("Created: unavailable;", format_file_dates(stat_result))

    def test_file_dates_use_windows_creation_time_on_older_python(self):
        stat_result = Mock(spec=["st_ctime", "st_mtime"], st_ctime=1_500_000_000, st_mtime=1_600_000_000)
        expected = datetime.fromtimestamp(stat_result.st_ctime).astimezone().isoformat(
            sep=" ", timespec="seconds"
        )
        with patch("tools.dedup_media.os.name", "nt"):
            self.assertIn(f"Created: {expected};", format_file_dates(stat_result))

    def test_describe_group_reads_current_dates_instead_of_cached_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "photo.jpg"
            path.write_bytes(b"image")
            os.utime(path, (1_600_000_000, 1_600_000_000))
            media_file = MediaFile(path, "photo.jpg", 5, "image/jpeg", "digest", 0)
            output = io.StringIO()
            with patch("sys.stdout", output):
                describe_group([media_file])
            self.assertIn(format_file_dates(path.stat()), output.getvalue())

    def test_file_url_uses_file_scheme_for_3gp_media(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.3GP"

            url = file_url(path)

            self.assertTrue(url.startswith("file:///"))
            self.assertTrue(url.endswith("clip.3GP"))

    def test_markdown_reference_index_reuses_supplied_media_files_for_filename_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            vault_root = Path(directory)
            markdown_path = vault_root / "note.md"
            markdown_path.write_text("[[portrait.jpg]]", encoding="utf-8")
            media_file = MediaFile(
                path=vault_root / "person" / "media" / "portrait.jpg",
                relative_path="person/media/portrait.jpg",
                size=1,
                mime_type="image/jpeg",
                digest="digest",
            )

            with patch("tools.dedup_media.media_file_paths") as media_file_paths_mock:
                reference_index = build_markdown_reference_index(vault_root, [media_file])

            self.assertEqual(reference_index.media_name_counts, {"portrait.jpg": 1})
            media_file_paths_mock.assert_not_called()

    def test_markdown_reference_index_reuses_unchanged_markdown_files(self):
        with tempfile.TemporaryDirectory() as directory:
            vault_root = Path(directory)
            markdown_path = vault_root / "note.md"
            markdown_path.write_text("[[people/jane/media/portrait.jpg]]", encoding="utf-8")
            media_file = MediaFile(
                path=vault_root / "people" / "jane" / "media" / "portrait.jpg",
                relative_path="people/jane/media/portrait.jpg",
                size=1,
                mime_type="image/jpeg",
                digest="digest",
            )

            first_index = build_markdown_reference_index(vault_root, [media_file])

            with patch("tools.dedup_media.read_markdown", side_effect=AssertionError("reread unchanged Markdown")):
                second_index = build_markdown_reference_index(
                    vault_root,
                    [media_file],
                    first_index.markdown_files,
                )

            self.assertEqual(
                second_index.wikilink_paths["people/jane/media/portrait.jpg"], {markdown_path}
            )

    def test_build_media_index_reuses_mime_type_for_unchanged_cached_file(self):
        with tempfile.TemporaryDirectory() as directory:
            vault_root = Path(directory)
            path = vault_root / "person" / "media" / "portrait.jpg"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"image")
            stat_result = path.stat()
            relative_path = path.relative_to(vault_root).as_posix()
            cached_file = MediaFile(
                path=path,
                relative_path=relative_path,
                size=stat_result.st_size,
                mime_type="image/jpeg",
                digest="cached-digest",
                modified_time_ns=stat_result.st_mtime_ns,
            )

            with patch("tools.dedup_media.detect_mime_type") as detect_mime_type_mock:
                media_files, _ = build_media_index(vault_root, {relative_path: cached_file})

            self.assertEqual(media_files[0].mime_type, "image/jpeg")
            self.assertEqual(media_files[0].digest, "cached-digest")
            detect_mime_type_mock.assert_not_called()

    def test_detect_mime_type_reads_only_the_file_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.jpg"
            path.write_bytes(b"\xff\xd8\xff" + b"x" * 1024)

            with patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read")):
                self.assertEqual(detect_mime_type(path), "image/jpeg")

    def test_relocate_media_file_uses_a_vault_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            vault_root = Path(directory)
            source = vault_root / "people" / "jane" / "media" / "portrait.jpg"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"image")
            media_file = MediaFile(
                path=source,
                relative_path="people/jane/media/portrait.jpg",
                size=source.stat().st_size,
                mime_type="image/jpeg",
                digest="digest",
                modified_time_ns=source.stat().st_mtime_ns,
            )

            relocated = relocate_media_file(
                media_file,
                "people/john/media/profile.jpg",
                vault_root,
            )

            self.assertEqual(relocated.relative_path, "people/john/media/profile.jpg")
            self.assertFalse(source.exists())
            self.assertEqual(relocated.path.read_bytes(), b"image")

    def test_relocate_media_file_accepts_a_leading_vault_root_slash(self):
        with tempfile.TemporaryDirectory() as directory:
            vault_root = Path(directory)
            source = vault_root / "people" / "jane" / "media" / "portrait.jpg"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"image")
            media_file = MediaFile(
                path=source,
                relative_path="people/jane/media/portrait.jpg",
                size=source.stat().st_size,
                mime_type="image/jpeg",
                digest="digest",
                modified_time_ns=source.stat().st_mtime_ns,
            )

            relocated = relocate_media_file(
                media_file,
                "/People/john/media/profile.jpg",
                vault_root,
            )

            self.assertEqual(relocated.relative_path.casefold(), "people/john/media/profile.jpg")
            self.assertTrue(relocated.path.is_file())

    def test_invalid_retention_choice_reprompts_for_the_same_group(self):
        with tempfile.TemporaryDirectory() as directory:
            vault_root = Path(directory)
            media_file = MediaFile(
                path=vault_root / "people" / "jane" / "media" / "portrait.jpg",
                relative_path="people/jane/media/portrait.jpg",
                size=1,
                mime_type="image/jpeg",
                digest="digest",
            )
            reference_index = MarkdownReferenceIndex(defaultdict(set), defaultdict(set), defaultdict(int))

            with patch("tools.dedup_media.describe_group") as describe_group, patch(
                "tools.dedup_media.prompt", side_effect=["/", "s"]
            ) as prompt:
                process_groups([[media_file]], vault_root, reference_index)

            self.assertEqual(describe_group.call_count, 1)
            self.assertEqual(prompt.call_count, 2)

    def test_large_group_reaches_prompt_without_destination_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group = []
            for index in range(253):
                path = root / f"copy{index}.jpg"
                path.write_bytes(b"same image")
                group.append(MediaFile(path, path.name, 10, "image/jpeg", "digest"))
            reference_index = MarkdownReferenceIndex(defaultdict(set), defaultdict(set), defaultdict(int))
            output = io.StringIO()
            with patch.object(Path, "exists", side_effect=AssertionError("destination check")), patch(
                "tools.dedup_media.prompt", return_value=None
            ) as prompt, patch("sys.stdout", output):
                process_groups([group], root, reference_index)
            prompt.assert_called_once()
            self.assertIn("[253]", output.getvalue())
            self.assertNotIn("[254]", output.getvalue())
            self.assertTrue(all(path.is_file() for path in root.iterdir()))

    def test_out_of_range_retention_choices_reprompt_without_removing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "photo.jpg"
            path.write_bytes(b"image")
            media_file = MediaFile(path, path.name, 5, "image/jpeg", "digest")
            reference_index = MarkdownReferenceIndex(defaultdict(set), defaultdict(set), defaultdict(int))
            with patch("tools.dedup_media.prompt", side_effect=["0", "-1", "2", "s"]) as prompt:
                process_groups([[media_file]], root, reference_index)
            self.assertEqual(prompt.call_count, 4)
            self.assertTrue(path.is_file())

    def test_main_handles_interruption_during_scan_or_listing(self):
        for interrupted_function in ("build_media_index", "describe_group"):
            with self.subTest(stage=interrupted_function), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                media_directory = root / "media"
                media_directory.mkdir()
                first = media_directory / "first.jpg"
                second = media_directory / "second.jpg"
                first.write_bytes(b"same image")
                second.write_bytes(b"same image")
                output_directory = root / "output"
                arguments = ["dedup_media.py", "-f", str(root), "-o", str(output_directory)]
                errors = io.StringIO()
                with patch("sys.argv", arguments), patch(
                    f"tools.dedup_media.{interrupted_function}", side_effect=KeyboardInterrupt
                ), patch("sys.stderr", errors):
                    self.assertEqual(main(), 130)
                self.assertIn("Interrupted.", errors.getvalue())
                self.assertNotIn("Traceback", errors.getvalue())
                self.assertTrue(first.is_file())
                self.assertTrue(second.is_file())
                self.assertEqual(
                    (output_directory / "media_dedup_index.json").is_file(),
                    interrupted_function == "describe_group",
                )

    def test_custom_path_relocates_first_file_and_removes_other_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            vault_root = Path(directory)
            first_path = vault_root / "People" / "jane" / "media" / "4f7d9e3b8a2c.jpg"
            second_path = vault_root / "People" / "john" / "media" / "9384726150.jpg"
            for path in (first_path, second_path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"same image")
            first = MediaFile(first_path, "People/jane/media/4f7d9e3b8a2c.jpg", 10, "image/jpeg", "digest")
            second = MediaFile(second_path, "People/john/media/9384726150.jpg", 10, "image/jpeg", "digest")
            reference_index = MarkdownReferenceIndex(defaultdict(set), defaultdict(set), defaultdict(int))

            with patch("tools.dedup_media.prompt", side_effect=["c", "People/jane/media/portrait.jpg"]):
                process_groups([[first, second]], vault_root, reference_index)

            self.assertTrue((vault_root / "People/jane/media/portrait.jpg").is_file())
            self.assertFalse(first_path.exists())
            self.assertFalse(second_path.exists())

    def test_zero_byte_files_are_not_grouped_as_duplicates_or_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file1 = root / "empty1.sql"
            file2 = root / "empty2.php"
            file1.write_bytes(b"")
            file2.write_bytes(b"")

            with patch("tools.dedup_media.sha256_file", side_effect=AssertionError("0-byte files should not be hashed")):
                media_files, groups = build_media_index(root, all_folders=True)

            self.assertEqual({f.path for f in media_files}, {file1, file2})
            self.assertEqual(groups, [])

    def test_handle_empty_files_deletes_when_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file1 = root / "empty1.txt"
            file2 = root / "empty2.txt"
            file1.write_bytes(b"")
            file2.write_bytes(b"")
            media_files = [
                MediaFile(file1, "empty1.txt", 0, "text/plain", ""),
                MediaFile(file2, "empty2.txt", 0, "text/plain", ""),
            ]
            with patch("tools.dedup_media.prompt", return_value="y"):
                deleted = handle_empty_files(media_files)

            self.assertEqual(len(deleted), 2)
            self.assertFalse(file1.exists())
            self.assertFalse(file2.exists())

    def test_handle_empty_files_preserves_when_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file1 = root / "empty1.txt"
            file1.write_bytes(b"")
            media_files = [MediaFile(file1, "empty1.txt", 0, "text/plain", "")]
            with patch("tools.dedup_media.prompt", return_value="n"):
                deleted = handle_empty_files(media_files)

            self.assertEqual(deleted, [])
            self.assertTrue(file1.is_file())

    def test_run_cleans_empty_files_and_processes_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty_file = root / "empty.txt"
            dup1 = root / "photo1.jpg"
            dup2 = root / "photo2.jpg"
            empty_file.write_bytes(b"")
            dup1.write_bytes(b"duplicate content")
            dup2.write_bytes(b"duplicate content")

            arguments = [
                "dedup_media.py", "-f", str(root), "--all-folders",
                "-o", str(root / "output"),
            ]
            # Prompt 1: delete empty files? -> 'y'
            # Prompt 2: choose duplicate keeper -> '1'
            with patch("sys.argv", arguments), patch(
                "tools.dedup_media.prompt", side_effect=["y", "1"]
            ):
                self.assertEqual(main(), 0)

            self.assertFalse(empty_file.exists())
            self.assertTrue(dup1.is_file())
            self.assertFalse(dup2.exists())
            self.assertTrue((root / "output" / "media_dedup_index.json").is_file())


if __name__ == "__main__":
    unittest.main()