import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from hal_md.organizations import (
    OrganizationsConfig,
    build_alias_index as _build_alias_index,
    normalize_organization_key,
    parse_organization_records as _parse_organization_records,
)


class OrganizationsConfigTests(unittest.TestCase):
    def test_unicode_keys_preserve_accents_but_normalize_composition_and_whitespace(self):
        self.assertEqual(
            normalize_organization_key("  UNIVERSITE\u0301\u00a0 Laval "),
            normalize_organization_key("Universit\u00e9 Laval"),
        )
        self.assertNotEqual(
            normalize_organization_key("Universite Laval"),
            normalize_organization_key("Universit\u00e9 Laval"),
        )

    def test_decomposed_alias_resolves_on_all_lookup_surfaces_without_prompt_or_write(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "organizations.json"
            original = json.dumps([{
                "name": "Universite Laval",
                "slug": "universite-laval",
                "aliases": ["Universit\u00e9 Laval"],
                "people": ["existing-person"],
            }])
            path.write_text(original, encoding="utf-8")
            config = OrganizationsConfig.load_optional(path.parent)
            config.prompt_for_unknown = True
            value = "  UNIVERSITE\u0301\u00a0 Laval "

            with patch("builtins.input", side_effect=AssertionError("unexpected prompt")), patch.object(
                config, "save", side_effect=AssertionError("unexpected write")
            ):
                self.assertEqual(config.split(value), ["Universite Laval"])
                self.assertEqual(config.slug_for_name(value), "universite-laval")
                self.assertEqual(config.slug_for_value(value), "universite-laval")
                self.assertEqual(config.resolve_unknown(value), "Universite Laval")
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_decomposed_compound_prefix_preserves_split_boundaries(self):
        config = OrganizationsConfig(records=_parse_organization_records([
            {"name": "Universite Laval", "aliases": ["Universit\u00e9 Laval"]},
            {"name": "McGill University"},
        ]))

        self.assertEqual(
            config.split("Universite\u0301 Laval and McGill University"),
            ["Universite Laval", "McGill University"],
        )

    def test_decomposed_registry_alias_matches_composed_input(self):
        config = OrganizationsConfig(records=_parse_organization_records([
            {"name": "Universite Laval", "aliases": ["Universite\u0301 Laval"]},
        ]))

        self.assertEqual(config.split("Universit\u00e9 Laval"), ["Universite Laval"])
        self.assertEqual(config.resolve_unknown("Universit\u00e9 Laval"), "Universite Laval")

    def test_unmatched_names_keep_their_unicode_spelling(self):
        value = "Universite\u0301 Laval"
        for records in ([], _parse_organization_records([{"name": "Other University"}])):
            with self.subTest(records=records):
                config = OrganizationsConfig(records=records)
                self.assertEqual(config.split(value), [value])

    def test_malformed_registry_is_reported_and_never_overwritten(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "organizations.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertLogs("hal_md.organizations", level="WARNING") as logs:
                config = OrganizationsConfig.load_optional(path.parent)
            self.assertIn("could not parse", logs.output[0])
            config.prompt_for_unknown = True
            with patch("builtins.input", side_effect=AssertionError("unexpected prompt")):
                self.assertEqual(config.resolve_unknown("Unknown"), "Unknown")
            self.assertEqual(path.read_text(encoding="utf-8"), "not json")

    def test_slug_for_value_matches_explicit_slug_not_derived_from_name(self):
        config = OrganizationsConfig(records=_parse_organization_records([
            {"name": "Universite Laval", "slug": "ulaval"},
        ]))

        self.assertEqual(config.slug_for_value("ulaval"), "ulaval")
        self.assertEqual(config.slug_for_value(""), "")

    def test_legacy_organization_name_and_aliases_are_parsed(self):
        config = OrganizationsConfig(records=_parse_organization_records([
            {"organization": "Universite Laval", "aliases:": "Universit\u00e9 Laval;ULaval"},
        ]))

        self.assertEqual(config.split("Universite\u0301 Laval"), ["Universite Laval"])
        self.assertEqual(config.split("ULaval"), ["Universite Laval"])

    def test_wrapped_registry_resolves_aliases_but_is_not_overwritten(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "organizations.json"
            original = json.dumps({"organizations": [
                {"name": "Universite Laval", "aliases": ["Universit\u00e9 Laval"]},
            ]})
            path.write_text(original, encoding="utf-8")
            with self.assertLogs("hal_md.organizations", level="WARNING"):
                config = OrganizationsConfig.load_optional(path.parent)
            config.prompt_for_unknown = True

            with patch("builtins.input", side_effect=AssertionError("unexpected prompt")):
                self.assertEqual(config.resolve_unknown("Universite\u0301 Laval"), "Universite Laval")
                self.assertEqual(config.resolve_unknown("Unknown"), "Unknown")
            with self.assertRaisesRegex(ValueError, "writable path"):
                config.save()
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_unknown_alias_preserves_record_metadata(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "organizations.json"
            path.write_text(json.dumps([{
                "name": "Canonical", "slug": "custom", "people": ["someone"], "extra": "keep",
            }]), encoding="utf-8")
            config = OrganizationsConfig.load_optional(path.parent)
            config.prompt_for_unknown = True

            with patch("builtins.input", return_value="Canonical"):
                self.assertEqual(config.resolve_unknown("New Alias"), "Canonical")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [{
                "name": "Canonical", "slug": "custom", "people": ["someone"], "extra": "keep",
                "aliases": ["New Alias"],
            }])

    def test_skip_unknown_is_cached_without_writing(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "organizations.json"
            path.write_text("[]", encoding="utf-8")
            config = OrganizationsConfig.load_optional(path.parent)
            config.prompt_for_unknown = True

            with patch("builtins.input", return_value="-") as prompt:
                self.assertEqual(config.resolve_unknown("Unknown"), "Unknown")
                self.assertEqual(config.resolve_unknown("Unknown"), "Unknown")
            prompt.assert_called_once()
            self.assertEqual(path.read_text(encoding="utf-8"), "[]")

    def test_parse_records_from_list(self):
        records = _parse_organization_records(
            [
                {"name": "Dun & Bradstreet", "slug": "dun-bradstreet", "aliases": ["D&B"]},
                {"name": "EduPristine"},
            ]
        )

        self.assertEqual([record.name for record in records], ["Dun & Bradstreet", "EduPristine"])
        self.assertEqual(records[0].slug, "dun-bradstreet")
        self.assertEqual(records[0].aliases, ("D&B",))

    def test_parse_records_from_wrapped_object(self):
        records = _parse_organization_records({"organizations": [{"name": "EduPristine"}]})

        self.assertEqual([record.name for record in records], ["EduPristine"])

    def test_parse_records_ignores_entries_without_a_name(self):
        records = _parse_organization_records([{"slug": "no-name"}, {"name": ""}])

        self.assertEqual(records, [])

    def test_split_returns_single_organization_when_no_config(self):
        config = OrganizationsConfig()

        self.assertEqual(config.split("Dun & Bradstreet and EduPristine"), ["Dun & Bradstreet and EduPristine"])

    def test_split_returns_single_organization_when_no_match(self):
        records = _parse_organization_records([{"name": "Acme Corp"}])
        config = OrganizationsConfig(records=records, alias_to_name=_build_alias_index(records))

        self.assertEqual(config.split("Unrelated Company"), ["Unrelated Company"])

    def test_split_separates_two_known_organizations_joined_by_and(self):
        records = _parse_organization_records(
            [
                {"name": "Dun & Bradstreet", "aliases": ["D&B"]},
                {"name": "EduPristine"},
            ]
        )
        config = OrganizationsConfig(records=records, alias_to_name=_build_alias_index(records))

        self.assertEqual(config.split("Dun & Bradstreet and EduPristine"), ["Dun & Bradstreet", "EduPristine"])

    def test_split_does_not_split_known_organization_on_plain_whitespace(self):
        records = _parse_organization_records([{"name": "Incognito"}, {"name": "Software"}])
        config = OrganizationsConfig(records=records, alias_to_name=_build_alias_index(records))

        self.assertEqual(config.split("Incognito Software"), ["Incognito Software"])

    def test_split_separates_two_known_organizations_joined_by_at(self):
        records = _parse_organization_records(
            [
                {"name": "Smith School of Business"},
                {"name": "Queen's University", "aliases": ["Queens University"]},
            ]
        )
        config = OrganizationsConfig(records=records, alias_to_name=_build_alias_index(records))

        self.assertEqual(
            config.split("Smith School of Business at Queens University"),
            ["Smith School of Business", "Queen's University"],
        )

    def test_split_separates_known_bilingual_organizations_joined_by_slash(self):
        records = _parse_organization_records(
            [
                {"name": "Swansea University"},
                {"name": "Prifysgol Abertawe"},
            ]
        )
        config = OrganizationsConfig(records=records, alias_to_name=_build_alias_index(records))

        self.assertEqual(
            config.split("Swansea University / Prifysgol Abertawe"),
            ["Swansea University", "Prifysgol Abertawe"],
        )

    def test_split_reorders_parent_university_school_suffix(self):
        records = _parse_organization_records(
            [
                {"name": "McGill University"},
                {"name": "School of Continuing Studies"},
            ]
        )
        config = OrganizationsConfig(records=records, alias_to_name=_build_alias_index(records))

        self.assertEqual(config.split("McGill University School of Continuing Studies"), ["McGill University"])

    def test_split_matches_known_alias_directly(self):
        records = _parse_organization_records([{"name": "Dun & Bradstreet", "aliases": ["D&B"]}])
        config = OrganizationsConfig(records=records, alias_to_name=_build_alias_index(records))

        self.assertEqual(config.split("D&B"), ["Dun & Bradstreet"])

    def test_slug_for_value_matches_a_slugified_alias(self):
        records = _parse_organization_records([{"name": "Nortel", "slug": "nortel", "aliases": ["Nortel Networks"]}])
        config = OrganizationsConfig(records=records, alias_to_name=_build_alias_index(records))

        self.assertEqual(config.slug_for_value("nortel-networks"), "nortel")

    def test_parse_records_tolerates_legacy_semicolon_delimited_alias_string(self):
        records = _parse_organization_records([{"name": "Schulich", "aliases": "Schulich ExecEd;Schulich Executive Education"}])

        self.assertEqual(records[0].aliases, ("Schulich ExecEd", "Schulich Executive Education"))

    def test_parse_records_tolerates_legacy_aliases_colon_typo_key(self):
        records = _parse_organization_records([{"name": "Aecon", "aliases:": ["Aecon Group Inc.", "Aecon Group"]}])

        self.assertEqual(records[0].aliases, ("Aecon Group Inc.", "Aecon Group"))

    def test_split_handles_possessive_apostrophe_after_known_alias(self):
        records = _parse_organization_records(
            [
                {"name": "SVKM", "aliases": ["Shri Vile Parle Kelavani Mandal"]},
                {"name": "Narsee Monjee Institute of Management Studies", "aliases": ["Narsee Monjee Institute of Management Studies (NMIMS)"]},
            ]
        )
        config = OrganizationsConfig(records=records, alias_to_name=_build_alias_index(records))

        self.assertEqual(
            config.split("SVKM's Narsee Monjee Institute of Management Studies (NMIMS)"),
            ["SVKM", "Narsee Monjee Institute of Management Studies"],
        )
        self.assertEqual(
            config.split("SVKM\u2019s Narsee Monjee Institute of Management Studies (NMIMS)"),
            ["SVKM", "Narsee Monjee Institute of Management Studies"],
        )

    def test_load_optional_returns_empty_config_when_file_missing(self):
        with TemporaryDirectory() as temp_dir:
            config = OrganizationsConfig.load_optional(Path(temp_dir))

        self.assertEqual(config.records, [])
        self.assertEqual(config.split("Anything"), ["Anything"])

    def test_load_optional_parses_organizations_json_from_config_folder(self):
        with TemporaryDirectory() as temp_dir:
            config_folder = Path(temp_dir)
            (config_folder / "organizations.json").write_text(
                '[{"name": "Dun & Bradstreet"}, {"name": "EduPristine"}]', encoding="utf-8"
            )

            config = OrganizationsConfig.load_optional(config_folder)

        self.assertEqual(config.split("Dun & Bradstreet and EduPristine"), ["Dun & Bradstreet", "EduPristine"])

    def test_load_optional_tolerates_malformed_json(self):
        with TemporaryDirectory() as temp_dir:
            config_folder = Path(temp_dir)
            (config_folder / "organizations.json").write_text("not json", encoding="utf-8")

            config = OrganizationsConfig.load_optional(config_folder)

        self.assertEqual(config.records, [])

    def test_resolve_unknown_adds_new_canonical_organization(self):
        with TemporaryDirectory() as temp_dir:
            config_folder = Path(temp_dir)
            path = config_folder / "organizations.json"
            path.write_text("[]", encoding="utf-8")
            config = OrganizationsConfig.load_optional(config_folder)

            self.assertEqual(config.resolve_unknown("New Organization"), "New Organization")
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(data, [{"name": "New Organization"}])

    def test_resolve_unknown_adds_shown_name_as_alias_of_entered_canonical_organization(self):
        with TemporaryDirectory() as temp_dir:
            config_folder = Path(temp_dir)
            path = config_folder / "organizations.json"
            path.write_text('[{"name": "Canonical Organization"}]', encoding="utf-8")
            config = OrganizationsConfig.load_optional(config_folder)
            config.prompt_for_unknown = True

            with patch("builtins.input", return_value="Canonical Organization"):
                self.assertEqual(config.resolve_unknown("LinkedIn Organization Name"), "Canonical Organization")
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(data, [{"name": "Canonical Organization", "aliases": ["LinkedIn Organization Name"]}])


if __name__ == "__main__":
    unittest.main()
