import io
import os
import tempfile
import unittest
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from tools.dedup_media import (
    FolderGroupEntry,
    FolderPreferenceRule,
    MarkdownReferenceIndex,
    MediaFile,
    PreferredPathRule,
    TreePreferenceRule,
    build_media_index,
    build_markdown_reference_index,
    detect_mime_type,
    describe_group,
    describe_folder_group,
    file_url,
    find_duplicate_folder_groups,
    find_path_prefix_difference,
    format_file_dates,
    handle_bak_files,
    handle_empty_files,
    main,
    parse_arguments,
    process_folder_groups,
    process_groups,
    relocate_media_file,
    resolve_group_with_rules,
    sha256_file,
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

    def test_find_duplicate_folder_groups_finds_identical_trees(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder_a = root / "FolderA"
            folder_b = root / "FolderB"
            for folder in (folder_a, folder_b):
                (folder / "sub").mkdir(parents=True)
                (folder / "file1.txt").write_bytes(b"content one")
                (folder / "sub" / "file2.txt").write_bytes(b"content two")

            media_files, _ = build_media_index(root, all_folders=True)
            folder_groups = find_duplicate_folder_groups(root, media_files)

            # Both root-level (FolderA vs FolderB) and subfolder-level (FolderA/sub vs FolderB/sub) match
            self.assertEqual(len(folder_groups), 2)
            # Shallowest folder group (depth 1) is first
            top_group = folder_groups[0]
            self.assertEqual({entry.path for entry in top_group}, {folder_a, folder_b})
            self.assertEqual(top_group[0].file_count, 2)
            self.assertEqual(top_group[0].total_size, len(b"content one") + len(b"content two"))

            child_group = folder_groups[1]
            self.assertEqual({entry.path for entry in child_group}, {folder_a / "sub", folder_b / "sub"})
            self.assertEqual(child_group[0].file_count, 1)

    def test_find_duplicate_folder_groups_excludes_unindexed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder_a = root / "FolderA"
            folder_b = root / "FolderB"
            for folder in (folder_a, folder_b):
                folder.mkdir()
                (folder / "file1.txt").write_bytes(b"content one")
            # Extra unindexed file in FolderB
            (folder_b / "extra.doc").write_bytes(b"extra")

            indexed_files = [
                MediaFile(folder_a / "file1.txt", "FolderA/file1.txt", 11, "text/plain", "hash1"),
                MediaFile(folder_b / "file1.txt", "FolderB/file1.txt", 11, "text/plain", "hash1"),
            ]
            folder_groups = find_duplicate_folder_groups(root, indexed_files)
            # FolderB contains extra.doc on disk not in indexed_files, so it should not match FolderA
            self.assertEqual(folder_groups, [])

    def test_process_folder_groups_deletes_folder_and_updates_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder_a = root / "FolderA"
            folder_b = root / "FolderB"
            for folder in (folder_a, folder_b):
                (folder / "sub").mkdir(parents=True)
                (folder / "pic.jpg").write_bytes(b"photo data")
                (folder / "sub" / "clip.mp4").write_bytes(b"video data")

            # Markdown note pointing to FolderB/sub/clip.mp4
            note = root / "note.md"
            note.write_text("See [[FolderB/sub/clip.mp4]]", encoding="utf-8")

            media_files, groups = build_media_index(root, all_folders=True)
            reference_index = build_markdown_reference_index(root, media_files)
            folder_groups = find_duplicate_folder_groups(root, media_files)

            # Choose option 1 (FolderA) to keep
            with patch("tools.dedup_media.prompt", return_value="1"):
                success = process_folder_groups(
                    folder_groups, root, reference_index, media_files, groups
                )

            self.assertTrue(success)
            self.assertTrue(folder_a.is_dir())
            self.assertFalse(folder_b.exists())
            self.assertIn("[[FolderA/sub/clip.mp4]]", note.read_text(encoding="utf-8"))
            # File groups should now be empty because folder dedup resolved them
            remaining_groups = [g for g in groups if len(g) > 1]
            self.assertEqual(remaining_groups, [])

    def test_process_folder_groups_skipping_allows_child_level_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder_a = root / "FolderA"
            folder_b = root / "FolderB"
            for folder in (folder_a, folder_b):
                (folder / "sub").mkdir(parents=True)
                (folder / "pic.jpg").write_bytes(b"photo data")
                (folder / "sub" / "clip.mp4").write_bytes(b"video data")

            media_files, groups = build_media_index(root, all_folders=True)
            reference_index = build_markdown_reference_index(root, media_files)
            folder_groups = find_duplicate_folder_groups(root, media_files)

            # Skip parent level ('s'), then select keeper for child level ('1')
            with patch("tools.dedup_media.prompt", side_effect=["s", "1"]):
                success = process_folder_groups(
                    folder_groups, root, reference_index, media_files, groups
                )

            self.assertTrue(success)
            # FolderA and FolderB still exist, but FolderB/sub was deleted
            self.assertTrue(folder_a.is_dir())
            self.assertTrue((folder_a / "sub").is_dir())
            self.assertTrue(folder_b.is_dir())
            self.assertFalse((folder_b / "sub").exists())

    def test_sha256_file_handles_missing_file(self):
        missing_path = Path("nonexistent_file_path_xyz.bin")
        self.assertEqual(sha256_file(missing_path), "")

    def test_format_file_dates_handles_missing_file(self):
        missing_path = Path("nonexistent_file_path_xyz.bin")
        self.assertEqual(format_file_dates(missing_path), "File or folder no longer exists")

    def test_build_media_index_handles_file_deleted_during_hashing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file1 = root / "image1.jpg"
            file2 = root / "image2.jpg"
            file3 = root / "image3.jpg"
            file1.write_bytes(b"content")
            file2.write_bytes(b"content")
            file3.write_bytes(b"content")

            original_sha = sha256_file

            def simulate_concurrent_delete(path: Path) -> str:
                if path.name == "image2.jpg":
                    path.unlink(missing_ok=True)
                    return ""
                return original_sha(path)

            with patch("tools.dedup_media.sha256_file", side_effect=simulate_concurrent_delete):
                media_files, groups = build_media_index(root, all_folders=True)

            self.assertEqual({f.path for f in media_files}, {file1, file3})
            self.assertEqual(len(groups), 1)
            self.assertEqual({f.path for f in groups[0]}, {file1, file3})

    def test_find_path_prefix_difference(self):
        # Case 1: nested prefix vs root with shared common subpath
        res = find_path_prefix_difference(
            "projects/janlabs/Phones/MISC/Screenshot.jpg",
            "janlabs/Phones/MISC/Screenshot.jpg",
        )
        self.assertEqual(res, ("projects/janlabs", "janlabs"))

        # Case 2: two differing root prefixes
        res = find_path_prefix_difference(
            "backupA/photos/vacation/img.jpg",
            "backupB/photos/vacation/img.jpg",
        )
        self.assertEqual(res, ("backupA", "backupB"))

        # Case 3: same parent, different filenames (no common suffix)
        res = find_path_prefix_difference("folder/a.jpg", "folder/b.jpg")
        self.assertIsNone(res)

    def test_resolve_group_with_rules(self):
        vault_root = Path("/vault")
        f1 = MediaFile(vault_root / "janlabs" / "photo.jpg", "janlabs/photo.jpg", 10, "image/jpeg", "h1")
        f2 = MediaFile(vault_root / "projects" / "janlabs" / "photo.jpg", "projects/janlabs/photo.jpg", 10, "image/jpeg", "h1")
        f3 = MediaFile(vault_root / "other" / "photo.jpg", "other/photo.jpg", 10, "image/jpeg", "h1")

        rule = FolderPreferenceRule("projects/janlabs", "janlabs")
        # In a 2-file group [f1, f2]: f2 is preferred over f1
        winner, matched_rule = resolve_group_with_rules([f1, f2], [rule], vault_root)
        self.assertEqual(winner, f2)
        self.assertEqual(matched_rule, rule)

        # In a 3-file group [f1, f2, f3]: f3 is unaddressed, so winner is not unique
        winner3, _ = resolve_group_with_rules([f1, f2, f3], [rule], vault_root)
        self.assertIsNone(winner3)

    def test_process_groups_auto_learns_repeated_folder_preference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Set 1
            s1_a = root / "janlabs" / "MISC" / "shot1.jpg"
            s1_b = root / "projects" / "janlabs" / "MISC" / "shot1.jpg"
            # Set 2
            s2_a = root / "janlabs" / "MISC" / "shot2.jpg"
            s2_b = root / "projects" / "janlabs" / "MISC" / "shot2.jpg"
            s2_c = root / "projects" / "janlabs" / "shot2.jpg"
            # Set 3 (should be auto-resolved once rule is learned!)
            s3_a = root / "janlabs" / "MISC" / "shot3.jpg"
            s3_b = root / "projects" / "janlabs" / "MISC" / "shot3.jpg"

            for path in (s1_a, s1_b, s2_a, s2_b, s2_c, s3_a, s3_b):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"content")

            m1_a = MediaFile(s1_a, s1_a.relative_to(root).as_posix(), 7, "image/jpeg", "h1")
            m1_b = MediaFile(s1_b, s1_b.relative_to(root).as_posix(), 7, "image/jpeg", "h1")
            m2_a = MediaFile(s2_a, s2_a.relative_to(root).as_posix(), 7, "image/jpeg", "h2")
            m2_b = MediaFile(s2_b, s2_b.relative_to(root).as_posix(), 7, "image/jpeg", "h2")
            m2_c = MediaFile(s2_c, s2_c.relative_to(root).as_posix(), 7, "image/jpeg", "h2")
            m3_a = MediaFile(s3_a, s3_a.relative_to(root).as_posix(), 7, "image/jpeg", "h3")
            m3_b = MediaFile(s3_b, s3_b.relative_to(root).as_posix(), 7, "image/jpeg", "h3")

            groups = [
                [m1_a, m1_b],
                [m2_a, m2_b, m2_c],
                [m3_a, m3_b],
            ]
            ref_index = MarkdownReferenceIndex(defaultdict(set), defaultdict(set), defaultdict(int))

            # Prompt sequence:
            # 1. Group 1: pick "2" (m1_b)
            # 2. Group 2: pick "2" (m2_b)
            # 3. Learning prompt triggers because projects/janlabs/MISC was picked over janlabs/MISC twice!
            #    User answers "1" (always prefer folder projects/janlabs/MISC over janlabs/MISC)
            # 4. Group 3: auto-selects m3_b without prompting!
            with patch("tools.dedup_media.prompt", side_effect=["2", "2", "1"]) as prompt_mock:
                process_groups(groups, root, ref_index)

            # Assert prompt was only called 3 times (the third group required 0 prompts!)
            self.assertEqual(prompt_mock.call_count, 3)

            # Verify kept files exist and duplicates are removed
            self.assertTrue(s1_b.is_file())
            self.assertFalse(s1_a.exists())

            self.assertTrue(s2_b.is_file())
            self.assertFalse(s2_a.exists())
            self.assertFalse(s2_c.exists())

            self.assertTrue(s3_b.is_file())
            self.assertFalse(s3_a.exists())

    def test_process_groups_explicit_remember_option_2a(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            s1_a = root / "janlabs" / "pic1.jpg"
            s1_b = root / "projects" / "janlabs" / "pic1.jpg"
            s2_a = root / "janlabs" / "pic2.jpg"
            s2_b = root / "projects" / "janlabs" / "pic2.jpg"

            for path in (s1_a, s1_b, s2_a, s2_b):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"content")

            m1_a = MediaFile(s1_a, s1_a.relative_to(root).as_posix(), 7, "image/jpeg", "h1")
            m1_b = MediaFile(s1_b, s1_b.relative_to(root).as_posix(), 7, "image/jpeg", "h1")
            m2_a = MediaFile(s2_a, s2_a.relative_to(root).as_posix(), 7, "image/jpeg", "h2")
            m2_b = MediaFile(s2_b, s2_b.relative_to(root).as_posix(), 7, "image/jpeg", "h2")

            groups = [[m1_a, m1_b], [m2_a, m2_b]]
            ref_index = MarkdownReferenceIndex(defaultdict(set), defaultdict(set), defaultdict(int))

            # User enters "2a" on group 1, then "1" to confirm folder preference.
            # Group 2 should be auto-resolved!
            with patch("tools.dedup_media.prompt", side_effect=["2a", "1"]) as prompt_mock:
                process_groups(groups, root, ref_index)

            self.assertEqual(prompt_mock.call_count, 2)
            self.assertTrue(s1_b.is_file())
            self.assertFalse(s1_a.exists())
            self.assertTrue(s2_b.is_file())
            self.assertFalse(s2_a.exists())

    def test_process_groups_with_cli_prefer_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            s1_a = root / "janlabs" / "pic1.jpg"
            s1_b = root / "projects" / "janlabs" / "pic1.jpg"

            for path in (s1_a, s1_b):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"content")

            m1_a = MediaFile(s1_a, s1_a.relative_to(root).as_posix(), 7, "image/jpeg", "h1")
            m1_b = MediaFile(s1_b, s1_b.relative_to(root).as_posix(), 7, "image/jpeg", "h1")

            groups = [[m1_a, m1_b]]
            ref_index = MarkdownReferenceIndex(defaultdict(set), defaultdict(set), defaultdict(int))
            rules = [PreferredPathRule("projects")]

            # Should auto-resolve without asking prompt
            with patch("tools.dedup_media.prompt") as prompt_mock:
                process_groups(groups, root, ref_index, rules=rules)

            prompt_mock.assert_not_called()
            self.assertTrue(s1_b.is_file())
            self.assertFalse(s1_a.exists())

    def test_handle_bak_files_deletes_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bak1 = root / "image.jpg.bak"
            bak2 = root / "data.sql.BAK"
            keep1 = root / "image.jpg"
            bak1.write_bytes(b"content")
            bak2.write_bytes(b"content")
            keep1.write_bytes(b"content")

            m_bak1 = MediaFile(bak1, "image.jpg.bak", 7, "application/octet-stream", "h1")
            m_bak2 = MediaFile(bak2, "data.sql.BAK", 7, "application/octet-stream", "h1")

            deleted = handle_bak_files([m_bak1, m_bak2], keep_bak=False)
            self.assertEqual(len(deleted), 2)
            self.assertFalse(bak1.exists())
            self.assertFalse(bak2.exists())
            self.assertTrue(keep1.is_file())

    def test_handle_bak_files_preserves_when_keep_bak_is_true(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bak1 = root / "image.jpg.bak"
            bak1.write_bytes(b"content")
            m_bak1 = MediaFile(bak1, "image.jpg.bak", 7, "application/octet-stream", "h1")

            deleted = handle_bak_files([m_bak1], keep_bak=True)
            self.assertEqual(deleted, [])
            self.assertTrue(bak1.is_file())

    def test_run_deletes_bak_files_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photo = root / "photo.jpg"
            photo_bak = root / "photo.jpg.bak"
            photo.write_bytes(b"photo content")
            photo_bak.write_bytes(b"photo content")

            arguments = [
                "dedup_media.py", "-f", str(root), "--all-folders",
                "-o", str(root / "output"),
            ]
            # Since photo.jpg.bak is deleted automatically, no duplicates remain and no prompt is shown.
            with patch("sys.argv", arguments), patch("tools.dedup_media.prompt") as prompt_mock:
                self.assertEqual(main(), 0)
                prompt_mock.assert_not_called()

            self.assertTrue(photo.is_file())
            self.assertFalse(photo_bak.exists())

    def test_run_preserves_bak_files_with_keep_bak(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            photo = root / "photo.jpg"
            photo_bak = root / "photo.jpg.bak"
            photo.write_bytes(b"photo content")
            photo_bak.write_bytes(b"photo content")

            arguments = [
                "dedup_media.py", "-f", str(root), "--all-folders",
                "-o", str(root / "output"), "--keep-bak",
            ]
            # Prompt 1: choose duplicate keeper -> '1' (keeping photo.jpg)
            with patch("sys.argv", arguments), patch(
                "tools.dedup_media.prompt", side_effect=["1"]
            ) as prompt_mock:
                self.assertEqual(main(), 0)
                self.assertEqual(prompt_mock.call_count, 1)

            self.assertTrue(photo.is_file())
            self.assertFalse(photo_bak.exists())

    def test_process_groups_delete_all_option_d(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            f1 = root / "copy1.jpg"
            f2 = root / "copy2.jpg"
            f1.write_bytes(b"image bytes")
            f2.write_bytes(b"image bytes")

            m1 = MediaFile(f1, "copy1.jpg", 11, "image/jpeg", "hash1")
            m2 = MediaFile(f2, "copy2.jpg", 11, "image/jpeg", "hash1")

            groups = [[m1, m2]]
            ref_index = MarkdownReferenceIndex(defaultdict(set), defaultdict(set), defaultdict(int))
            with patch("tools.dedup_media.prompt", side_effect=["d"]):
                process_groups(groups, root, ref_index)

            self.assertFalse(f1.exists())
            self.assertFalse(f2.exists())

    def test_process_folder_groups_delete_all_option_d(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder1 = root / "folder1"
            folder2 = root / "folder2"
            folder1.mkdir()
            folder2.mkdir()
            f1 = folder1 / "item.jpg"
            f2 = folder2 / "item.jpg"
            f1.write_bytes(b"content")
            f2.write_bytes(b"content")

            m1 = MediaFile(f1, "folder1/item.jpg", 7, "image/jpeg", "h")
            m2 = MediaFile(f2, "folder2/item.jpg", 7, "image/jpeg", "h")

            entry1 = FolderGroupEntry(folder1, 1, 7, (m1,))
            entry2 = FolderGroupEntry(folder2, 1, 7, (m2,))
            folder_groups = [[entry1, entry2]]

            ref_index = MarkdownReferenceIndex(defaultdict(set), defaultdict(set), defaultdict(int))
            media_files = [m1, m2]
            groups = [[m1, m2]]

            with patch("tools.dedup_media.prompt", side_effect=["d"]):
                process_folder_groups(folder_groups, root, ref_index, media_files, groups)

            self.assertFalse(folder1.exists())
            self.assertFalse(folder2.exists())
            self.assertEqual(media_files, [])
            self.assertEqual(groups, [[]])


if __name__ == "__main__":
    unittest.main()