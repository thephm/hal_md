import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.extract_organizations import find_existing, normalize_existing_record
from tools.merge_person_files import load_organization_aliases, normalized_position_organization


class OrganizationConsumerTests(unittest.TestCase):
    def test_extractor_matches_decomposed_legacy_alias(self):
        record = {"name": "Universite Laval", "slug": "ulaval", "aliases:": "Universit\u00e9 Laval;UL"}

        self.assertIs(find_existing([record], "Universite\u0301 Laval"), record)
        normalize_existing_record(record)
        self.assertEqual(record["aliases"], ["Universit\u00e9 Laval", "UL"])
        self.assertNotIn("aliases:", record)

    def test_merge_uses_shared_legacy_record_and_alias_parsing(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "organizations.json"
            path.write_text(json.dumps({"organizations": [{
                "organization": "Universite Laval",
                "aliases:": "Universit\u00e9 Laval;ULaval",
            }]}), encoding="utf-8")

            aliases = load_organization_aliases(path)

        for name in ("Universite Laval", "Universite\u0301 Laval", "ULaval"):
            self.assertEqual(aliases[normalized_position_organization(name)], "Universite Laval")
        self.assertEqual(aliases["kindryl"], "Kyndryl")


if __name__ == "__main__":
    unittest.main()
