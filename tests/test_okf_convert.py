import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import yaml

from tools.okf_convert import (
    convert_text,
    load_type_map,
    main,
    normalize_tag,
)


def frontmatter(*lines):
    return "\n".join(["---", *lines, "---", "", "# Body", ""])


TYPE_MAP = {"person": "Person", "chat": "Chat", "email": "email", "dog": "Pet"}


class ConvertTextTests(unittest.TestCase):
    def test_scalar_tag_converts_and_preserves_comment_and_crlf(self):
        text = frontmatter(
            "title: Entry", "tags: 'technology'  # keep", "other: value"
        ).replace("\n", "\r\n")
        converted, type_name = convert_text(text, {"technology": "Technology"})
        self.assertEqual(type_name, "Technology")
        self.assertEqual(
            converted,
            frontmatter(
                "type: Technology", "title: Entry", "tags:  # keep", "  - ",
                "other: value",
            ).replace("\n", "\r\n"),
        )

    def test_scalar_unknown_or_existing_type_is_skipped(self):
        with self.assertRaisesRegex(ValueError, "no tag matches"):
            convert_text(frontmatter("tags: unknown"), {"technology": "Technology"})
        with self.assertRaisesRegex(ValueError, "already has a type"):
            convert_text(
                frontmatter("tags: technology", "type: Technology"),
                {"technology": "Technology"},
            )

    def test_converts_inline_tags_to_block_list(self):
        text = frontmatter("tags: [chat, project-x]", "service: signal")
        converted, type_name = convert_text(text, TYPE_MAP)
        self.assertEqual(type_name, "Chat")
        self.assertEqual(
            converted,
            frontmatter("type: Chat", "tags:", "  - project-x", "service: signal"),
        )

    def test_matches_first_known_inline_tag_anywhere(self):
        text = frontmatter("tags: [project-x, chat, person, project-x]")
        converted, type_name = convert_text(text, TYPE_MAP)
        self.assertEqual(type_name, "Chat")
        self.assertEqual(
            converted,
            frontmatter(
                "type: Chat", "tags:", "  - project-x", "  - person", "  - project-x"
            ),
        )

    def test_inline_type_only_keeps_blank_item(self):
        for value in ("[person]", "[null, person, null]"):
            with self.subTest(value=value):
                converted, _ = convert_text(frontmatter(f"tags: {value}"), TYPE_MAP)
                self.assertEqual(
                    converted, frontmatter("type: Person", "tags:", "  - ")
                )

    def test_inline_quotes_escapes_and_punctuation_preserve_tag_values(self):
        value = r"""['#PERSON', 'a,b', "a\"b", 'x[y]', 'it''s', "#topic", "yes"]"""
        converted, type_name = convert_text(frontmatter(f"tags: {value}"), TYPE_MAP)
        self.assertEqual(type_name, "Person")
        properties = yaml.safe_load(converted.split("---", 2)[1])
        self.assertEqual(
            properties["tags"], ["a,b", 'a"b', "x[y]", "it's", "#topic", "yes"]
        )

    def test_inline_preserves_other_fields_body_comment_and_crlf(self):
        text = frontmatter(
            "# Note metadata",
            "title: 'A title'",
            'tags: ["chat", project-x]  # keep this comment',
            "people: [ann, bob]",
        ).replace("\n", "\r\n")
        converted, _ = convert_text(text, TYPE_MAP)
        self.assertEqual(
            converted,
            frontmatter(
                "type: Chat",
                "# Note metadata",
                "title: 'A title'",
                "tags:  # keep this comment",
                "  - project-x",
                "people: [ann, bob]",
            ).replace("\n", "\r\n"),
        )

    def test_inline_skips_empty_unknown_and_already_typed(self):
        for value in ("[]", "[unknown]"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "no tag matches"):
                    convert_text(frontmatter(f"tags: {value}"), TYPE_MAP)
        with self.assertRaisesRegex(ValueError, "already has a type"):
            convert_text(frontmatter("tags: [person]", "type: Person"), TYPE_MAP)

    def test_inline_conversion_is_idempotent(self):
        converted, _ = convert_text(frontmatter("tags: [person, other]"), TYPE_MAP)
        with self.assertRaisesRegex(ValueError, "already has a type"):
            convert_text(converted, TYPE_MAP)

    def test_moves_first_tag_to_type_field(self):
        text = frontmatter("tags:", "  - person", "  - other", "first_name: Ann")
        converted, type_name = convert_text(text, TYPE_MAP)
        self.assertEqual(type_name, "Person")
        self.assertEqual(
            converted,
            frontmatter("type: Person", "tags:", "  - other", "first_name: Ann"),
        )

    def test_matches_a_later_tag(self):
        text = frontmatter("tags:", "  - unknown", "  - chat")
        converted, type_name = convert_text(text, TYPE_MAP)
        self.assertEqual(type_name, "Chat")
        self.assertEqual(converted, frontmatter("type: Chat", "tags:", "  - unknown"))

    def test_keeps_empty_tag_item_when_list_becomes_empty(self):
        text = frontmatter("tags:", "  - person", "slug: ann")
        converted, _ = convert_text(text, TYPE_MAP)
        self.assertEqual(
            converted, frontmatter("type: Person", "tags:", "  - ", "slug: ann")
        )

    def test_collapses_blank_items_to_one_empty_item(self):
        text = frontmatter("tags:", "  - ", "  - person", "  - ")
        converted, _ = convert_text(text, TYPE_MAP)
        self.assertEqual(converted, frontmatter("type: Person", "tags:", "  - "))

    def test_matches_quoted_and_hash_prefixed_tags_case_insensitively(self):
        for item in ('"Person"', "'person'", "#person", "PERSON"):
            with self.subTest(item=item):
                _, type_name = convert_text(
                    frontmatter("tags:", f"  - {item}"), TYPE_MAP
                )
                self.assertEqual(type_name, "Person")

    def test_preserves_crlf_line_endings(self):
        text = frontmatter("tags:", "  - person").replace("\n", "\r\n")
        converted, _ = convert_text(text, TYPE_MAP)
        self.assertEqual(
            converted, frontmatter("type: Person", "tags:", "  - ").replace("\n", "\r\n")
        )

    def test_skips_file_without_frontmatter(self):
        for text in ("# Heading\n", "", "---\nnever closed\n"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "no frontmatter"):
                    convert_text(text, TYPE_MAP)

    def test_skips_file_that_already_has_a_type(self):
        for existing in ("type: Person", "Type: Post"):
            with self.subTest(existing=existing):
                text = frontmatter(existing, "tags:", "  - person")
                with self.assertRaisesRegex(ValueError, "already has a type"):
                    convert_text(text, TYPE_MAP)

    def test_skips_file_without_matching_tag(self):
        with self.assertRaisesRegex(ValueError, "no tag matches"):
            convert_text(frontmatter("tags:", "  - unknown"), TYPE_MAP)
        with self.assertRaisesRegex(ValueError, "no tags field"):
            convert_text(frontmatter("slug: ann"), TYPE_MAP)

    def test_does_not_match_tags_in_the_body(self):
        text = "\n".join(
            ["---", "slug: ann", "---", "", "tags:", "  - person", ""]
        )
        with self.assertRaisesRegex(ValueError, "no tags field"):
            convert_text(text, TYPE_MAP)

    def test_normalize_tag(self):
        self.assertEqual(normalize_tag('  "#Person" '), "person")


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.templates = self.root / "Templates"
        self.templates.mkdir()
        self.template("Person.md", "type: Person")
        self.template("Post.md", "Type: Post")
        self.template("No Type.md", "slug: ")
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))

    def template(self, name, *lines):
        (self.templates / name).write_text(frontmatter(*lines), encoding="utf-8")

    def note(self, name, text, encoding="utf-8"):
        path = self.root / name
        path.write_text(text, encoding=encoding, newline="\n")
        return path

    def run_main(self, *extra):
        return main(
            [
                "--root",
                str(self.root),
                "--templates",
                str(self.templates),
                *extra,
            ]
        )

    def test_load_type_map_reads_templates(self):
        self.assertEqual(
            load_type_map(self.templates), {"person": "Person", "post": "Post"}
        )

    def test_dry_run_reports_without_writing(self):
        original = frontmatter("tags:", "  - person")
        path = self.note("ann.md", original)
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertNotIn("would convert [Person]", self.output.getvalue())
        self.assertIn("converted: 1 (dry run", self.output.getvalue())

    def test_dry_run_lists_skipped_files_and_errors_but_not_convertible_files(self):
        convertible = self.note("convertible.md", frontmatter("tags: [person]"))
        unknown = self.note("unknown.md", frontmatter("tags: [unrecognized]"))
        no_tags = self.note("no-tags.md", frontmatter("title: Entry"))
        no_frontmatter = self.note("no-frontmatter.md", "# Entry\n")
        typed = self.note("typed.md", frontmatter("type: Person", "tags: [other]"))
        invalid_utf8 = self.root / "invalid-utf8.md"
        invalid_utf8.write_bytes(b"\xff")
        invalid_list = self.note("invalid-list.md", frontmatter("tags: [person"))
        snapshots = {path: path.read_bytes() for path in (
            convertible, unknown, no_tags, no_frontmatter, typed, invalid_utf8, invalid_list
        )}

        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(self.run_main(), 1)

        output = self.output.getvalue()
        self.assertNotIn("would convert", output)
        self.assertNotIn(str(convertible), output)
        for path, reason in (
            (unknown, "no tag matches a known type"),
            (typed, "already has a type field"),
            (invalid_utf8, "not valid UTF-8"),
        ):
            with self.subTest(path=path):
                self.assertIn(f"skipped ({reason}): {path}", output)
        self.assertNotIn(str(no_tags), output)
        self.assertNotIn(str(no_frontmatter), output)
        self.assertIn("skipped, no tags field: 1", output)
        self.assertIn("skipped, no frontmatter: 1", output)
        self.assertIn(f"error: {invalid_list}: invalid inline tags", errors.getvalue())
        self.assertIn("converted: 1 (dry run", output)
        self.assertIn("errors: 1", output)
        for path, original in snapshots.items():
            self.assertEqual(path.read_bytes(), original)

    def test_dry_run_verbose_does_not_list_convertible_files(self):
        self.note("ann.md", frontmatter("tags: [person]"))
        no_tags = self.note("no-tags.md", frontmatter("title: Entry"))
        no_frontmatter = self.note("no-frontmatter.md", "# Entry\n")
        unknown = self.note("unknown.md", frontmatter("tags: [unrecognized]"))
        self.assertEqual(self.run_main("--verbose"), 0)
        self.assertNotIn("would convert", self.output.getvalue())
        self.assertNotIn(str(no_tags), self.output.getvalue())
        self.assertNotIn(str(no_frontmatter), self.output.getvalue())
        self.assertIn(f"skipped (no tag matches a known type): {unknown}", self.output.getvalue())
        self.assertIn("skipped, no tags field: 1", self.output.getvalue())
        self.assertIn("skipped, no frontmatter: 1", self.output.getvalue())
        self.assertIn("converted: 1 (dry run", self.output.getvalue())

    def test_apply_writes_changes(self):
        path = self.note("ann.md", frontmatter("tags:", "  - person"))
        skipped = self.note("unknown.md", frontmatter("tags:", "  - unknown"))
        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual(
            path.read_text(encoding="utf-8"),
            frontmatter("type: Person", "tags:", "  - "),
        )
        self.assertEqual(skipped.read_text(encoding="utf-8"), frontmatter("tags:", "  - unknown"))
        self.assertIn("skipped, no tag matches a known type: 1", self.output.getvalue())
        self.assertIn(f"converted [Person]: {path}", self.output.getvalue())
        self.assertNotIn(f"skipped (no tag matches a known type): {skipped}", self.output.getvalue())

    def test_apply_verbose_reports_skips(self):
        unknown = self.note("unknown.md", frontmatter("tags: [unrecognized]"))
        no_tags = self.note("no-tags.md", frontmatter("title: Entry"))
        no_frontmatter = self.note("no-frontmatter.md", "# Entry\n")
        typed = self.note("typed.md", frontmatter("type: Person", "tags: [other]"))
        self.assertEqual(self.run_main("--apply", "--verbose"), 0)
        self.assertIn(
            f"skipped (no tag matches a known type): {unknown}", self.output.getvalue()
        )
        self.assertNotIn(f"skipped (already has a type field): {typed}", self.output.getvalue())
        self.assertNotIn(str(no_tags), self.output.getvalue())
        self.assertNotIn(str(no_frontmatter), self.output.getvalue())
        self.assertIn("skipped, no tags field: 1", self.output.getvalue())
        self.assertIn("skipped, no frontmatter: 1", self.output.getvalue())

    def test_note_maps_to_note_type_by_default(self):
        block = self.note(
            "block.md", frontmatter("tags:", "  - other", "  - note", "title: Entry")
        )
        inline = self.note("inline.md", frontmatter("tags: [note, other]"))
        alone = self.note("alone.md", frontmatter("tags: [note]"))

        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual(
            block.read_text(encoding="utf-8"),
            frontmatter("type: Note", "tags:", "  - other", "title: Entry"),
        )
        self.assertEqual(
            inline.read_text(encoding="utf-8"),
            frontmatter("type: Note", "tags:", "  - other"),
        )
        self.assertEqual(
            alone.read_text(encoding="utf-8"), frontmatter("type: Note", "tags:", "  - ")
        )

    def test_technology_maps_by_default_for_scalar_block_and_inline(self):
        scalar = self.note("scalar.md", frontmatter("tags: technology", "title: Entry"))
        block = self.note(
            "block.md", frontmatter("tags:", "  - other", "  - technology")
        )
        inline = self.note("inline.md", frontmatter("tags: [technology, other]"))
        original = scalar.read_bytes()
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(scalar.read_bytes(), original)
        self.assertIn("converted: 3 (dry run", self.output.getvalue())

        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual(
            scalar.read_text(encoding="utf-8"),
            frontmatter("type: Technology", "tags:", "  - ", "title: Entry"),
        )
        expected = frontmatter("type: Technology", "tags:", "  - other")
        self.assertEqual(block.read_text(encoding="utf-8"), expected)
        self.assertEqual(inline.read_text(encoding="utf-8"), expected)

    def test_invalid_scalar_tags_are_reported_without_writes(self):
        for value in ('"unterminated', "{key: value}", "|", "&anchor technology", "true"):
            with self.subTest(value=value):
                path = self.note("invalid.md", frontmatter(f"tags: {value}"))
                original = path.read_bytes()
                errors = io.StringIO()
                with redirect_stderr(errors):
                    self.assertEqual(self.run_main("--apply"), 1)
                self.assertEqual(path.read_bytes(), original)
                self.assertIn(str(path), errors.getvalue())
                self.assertIn("invalid scalar tags", errors.getvalue())

    def test_scalar_tag_with_continuation_is_not_converted(self):
        path = self.note(
            "continued.md", frontmatter("tags: technology", "  continuation")
        )
        original = path.read_bytes()
        errors = io.StringIO()
        with redirect_stderr(errors):
            self.assertEqual(self.run_main("--apply"), 1)
        self.assertEqual(path.read_bytes(), original)
        self.assertIn("invalid scalar tags", errors.getvalue())

    def test_technology_mapping_can_be_overridden(self):
        path = self.note("technology.md", frontmatter("tags: technology"))
        self.assertEqual(self.run_main("--apply", "--map", "technology=Tech"), 0)
        self.assertEqual(
            path.read_text(encoding="utf-8"),
            frontmatter("type: Tech", "tags:", "  - "),
        )

    def test_service_tag_maps_by_default_without_changing_service_field(self):
        scalar = self.note(
            "scalar.md", frontmatter("tags: service", "service: signal")
        )
        block = self.note(
            "block.md", frontmatter("tags:", "  - service", "  - other")
        )
        inline = self.note("inline.md", frontmatter("tags: [other, service]"))
        untouched = self.note(
            "not-a-service-tag.md", frontmatter("tags: [person]", "service: signal")
        )
        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual(
            scalar.read_text(encoding="utf-8"),
            frontmatter("type: Service", "tags:", "  - ", "service: signal"),
        )
        expected = frontmatter("type: Service", "tags:", "  - other")
        self.assertEqual(block.read_text(encoding="utf-8"), expected)
        self.assertEqual(inline.read_text(encoding="utf-8"), expected)
        self.assertEqual(
            untouched.read_text(encoding="utf-8"),
            frontmatter("type: Person", "tags:", "  - ", "service: signal"),
        )

    def test_resource_tag_maps_by_default_for_scalar_block_and_inline(self):
        scalar = self.note("scalar.md", frontmatter("tags: resource"))
        block = self.note("block.md", frontmatter("tags:", "  - resource", "  - other"))
        inline = self.note("inline.md", frontmatter("tags: [other, resource]"))
        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual(
            scalar.read_text(encoding="utf-8"),
            frontmatter("type: Resource", "tags:", "  - "),
        )
        expected = frontmatter("type: Resource", "tags:", "  - other")
        self.assertEqual(block.read_text(encoding="utf-8"), expected)
        self.assertEqual(inline.read_text(encoding="utf-8"), expected)

    def test_meetings_tag_maps_by_default_for_scalar_block_and_inline(self):
        scalar = self.note("scalar.md", frontmatter("tags: meetings"))
        block = self.note("block.md", frontmatter("tags:", "  - other", "  - meetings"))
        inline = self.note("inline.md", frontmatter("tags: [meetings, other]"))
        singular = self.note("singular.md", frontmatter("tags: meeting"))
        original = {path: path.read_bytes() for path in (scalar, block, inline, singular)}

        self.assertEqual(self.run_main(), 0)
        self.assertIn("converted: 4 (dry run", self.output.getvalue())
        for path, data in original.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(self.run_main("--apply"), 0)
        empty = frontmatter("type: Meeting", "tags:", "  - ")
        self.assertEqual(scalar.read_text(encoding="utf-8"), empty)
        self.assertEqual(singular.read_text(encoding="utf-8"), empty)
        expected = frontmatter("type: Meeting", "tags:", "  - other")
        self.assertEqual(block.read_text(encoding="utf-8"), expected)
        self.assertEqual(inline.read_text(encoding="utf-8"), expected)

    def test_tool_tag_sets_app_and_preserves_original_tags(self):
        examples = (
            ("scalar.md", frontmatter("tags: 'tool'  # keep", "title: Item")),
            ("block.md", frontmatter("tags:", "  - other", "  - tool", "  - extra")),
            ("inline.md", frontmatter('tags: [other, "#TOOL", extra]  # keep')),
        )
        paths = [(self.note(name, text), text) for name, text in examples]

        self.assertEqual(self.run_main(), 0)
        self.assertIn("converted: 3 (dry run", self.output.getvalue())
        for path, text in paths:
            self.assertEqual(path.read_bytes(), text.encode("utf-8"))

        self.assertEqual(self.run_main("--apply"), 0)
        for path, text in paths:
            self.assertEqual(
                path.read_bytes(), text.replace("---\n", "---\ntype: App\n", 1).encode("utf-8")
            )
        self.assertEqual(self.run_main("--apply"), 0)
        for path, text in paths:
            self.assertEqual(
                path.read_bytes(), text.replace("---\n", "---\ntype: App\n", 1).encode("utf-8")
            )

    def test_tool_tag_preserves_first_match_rule_and_other_type_tags(self):
        first_tool = self.note("tool-first.md", frontmatter("tags: [tool, person]"))
        first_person = self.note("person-first.md", frontmatter("tags: [person, tool]"))
        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual(
            first_tool.read_text(encoding="utf-8"),
            frontmatter("type: App", "tags: [tool, person]"),
        )
        self.assertEqual(
            first_person.read_text(encoding="utf-8"),
            frontmatter("type: Person", "tags:", "  - tool"),
        )

    def test_tool_mapping_override_still_preserves_tag(self):
        path = self.note("override.md", frontmatter("tags: tool"))
        self.assertEqual(self.run_main("--apply", "--map", "tool=CustomTool"), 0)
        self.assertEqual(
            path.read_text(encoding="utf-8"),
            frontmatter("type: CustomTool", "tags: tool"),
        )

    def test_app_tag_maps_by_default_for_scalar_block_and_inline(self):
        scalar = self.note("scalar.md", frontmatter("tags: app"))
        block = self.note("block.md", frontmatter("tags:", "  - app", "  - other"))
        inline = self.note("inline.md", frontmatter("tags: [other, app]"))
        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual(
            scalar.read_text(encoding="utf-8"),
            frontmatter("type: App", "tags:", "  - "),
        )
        expected = frontmatter("type: App", "tags:", "  - other")
        self.assertEqual(block.read_text(encoding="utf-8"), expected)
        self.assertEqual(inline.read_text(encoding="utf-8"), expected)

    def test_note_mapping_can_be_overridden(self):
        path = self.note("note.md", frontmatter("tags: [note]"))
        self.assertEqual(self.run_main("--apply", "--map", "note=CustomNote"), 0)
        self.assertEqual(
            path.read_text(encoding="utf-8"),
            frontmatter("type: CustomNote", "tags:", "  - "),
        )

    def test_inline_cli_dry_run_apply_and_rerun(self):
        original = frontmatter("tags: [other, person]", "slug: ann").replace(
            "\n", "\r\n"
        )
        path = self.note("ann.md", original, encoding="utf-8-sig")
        before = path.read_bytes()
        self.assertEqual(self.run_main(), 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("would convert [Person]", self.output.getvalue())
        self.assertEqual(self.run_main("--apply"), 0)
        expected = frontmatter(
            "type: Person", "tags:", "  - other", "slug: ann"
        ).replace("\n", "\r\n")
        self.assertEqual(path.read_bytes(), expected.encode("utf-8-sig"))
        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual(path.read_bytes(), expected.encode("utf-8-sig"))
        self.assertIn("already has a type field: 1", self.output.getvalue())

    def test_invalid_inline_lists_report_errors_without_writes(self):
        for value in ("[person", "[person, [nested]]", "[person, {key: value}]",
                      "[person, 123]", "[person, true]"):
            with self.subTest(value=value):
                path = self.note("invalid.md", frontmatter(f"tags: {value}"))
                original = path.read_bytes()
                errors = io.StringIO()
                with redirect_stderr(errors):
                    self.assertEqual(self.run_main("--apply"), 1)
                self.assertEqual(path.read_bytes(), original)
                self.assertIn(str(path), errors.getvalue())
                self.assertIn("invalid inline tags", errors.getvalue())

    def test_apply_preserves_utf8_bom(self):
        path = self.note("ann.md", frontmatter("tags:", "  - person"), encoding="utf-8-sig")
        self.assertEqual(self.run_main("--apply"), 0)
        data = path.read_bytes()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(
            data.decode("utf-8-sig"), frontmatter("type: Person", "tags:", "  - ")
        )

    def test_extra_mappings_from_defaults_and_map_option(self):
        dog = self.note("rex.md", frontmatter("tags:", "  - dog"))
        idea = self.note("idea.md", frontmatter("tags:", "  - idea"))
        self.assertEqual(self.run_main("--apply", "--map", "idea=Idea"), 0)
        self.assertIn("type: Pet", dog.read_text(encoding="utf-8"))
        self.assertIn("type: Idea", idea.read_text(encoding="utf-8"))

    def test_excluded_folders_are_skipped(self):
        hidden = self.root / ".obsidian"
        hidden.mkdir()
        original = frontmatter("tags:", "  - person")
        path = self.note(".obsidian/config.md", original)
        template = self.templates / "Person.md"
        template_text = template.read_text(encoding="utf-8")
        self.assertEqual(self.run_main("--apply"), 0)
        self.assertEqual(path.read_text(encoding="utf-8"), original)
        self.assertEqual(template.read_text(encoding="utf-8"), template_text)


if __name__ == "__main__":
    unittest.main()
