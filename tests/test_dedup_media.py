import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from tools.dedup_media import (
    MarkdownReferenceIndex,
    MediaFile,
    cross_location_filename_options,
    process_groups,
    relocate_media_file,
)


class DedupMediaTests(unittest.TestCase):
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

    def test_cross_location_filename_options_follow_display_order(self):
        first = MediaFile(Path("People/bernie/media/first.jpg"), "People/bernie/media/first.jpg", 1, "image/jpeg", "digest")
        second = MediaFile(Path("People/bernie/media/second.jpg"), "People/bernie/media/second.jpg", 1, "image/jpeg", "digest")
        third = MediaFile(Path("People/bernie/media/third.jpg"), "People/bernie/media/third.jpg", 1, "image/jpeg", "digest")

        options = cross_location_filename_options([first, second, third])

        self.assertEqual(options, [
            (first, second),
            (first, third),
            (second, first),
            (second, third),
            (third, first),
            (third, second),
        ])


if __name__ == "__main__":
    unittest.main()