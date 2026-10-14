import unittest

import yaml

from tools import extract_organizations as eo


class ExtractOrganizationsTests(unittest.TestCase):
    def test_organization_slug_length_limit_is_inclusive(self):
        self.assertTrue(eo.is_valid_organization_slug("a" * 64))
        self.assertFalse(eo.is_valid_organization_slug("a" * 65))

    def test_educational_experience_summary_is_not_an_organization(self):
        for value in (
            "3-educational-experiences-at-university-of-toronto-and-2-other-schools",
            "2-educational-experiences",
            "3 educational experiences at University of Toronto",
            "a" * 65,
        ):
            with self.subTest(value=value):
                organizations = []
                self.assertIsNone(eo.ensure_organization(organizations, value))
                self.assertEqual(organizations, [])

    def test_blank_frontmatter_organization_list_item_is_ignored(self):
        frontmatter = yaml.safe_load("organizations:\n  -\n")

        self.assertEqual(eo.get_list_field(frontmatter, "organizations"), [])

    def test_placeholder_organization_values_do_not_link_person_to_ignore(self):
        organizations = [
            {
                "name": "Ignore",
                "slug": "ignore",
                "aliases": ["None", "TBD", "Undisclosed"],
                "people": [],
            }
        ]

        result = eo.ensure_organization(organizations, "None", person_slug="blank-person")

        self.assertIsNone(result)
        self.assertEqual(organizations[0]["people"], [])

    def test_wheelabrator_variants_are_canonicalized_as_aliases(self):
        organizations = [
            {
                "name": "Wheelabrator Group",
                "slug": "wheelabrator-group",
                "aliases": [],
                "people": [],
            }
        ]

        eo.normalize_existing_record(organizations[0])
        result = eo.ensure_organization(organizations, "Wheelabrator Canada")

        self.assertIs(result, organizations[0])
        self.assertEqual(organizations[0]["name"], "Wheelabrator")
        self.assertEqual(
            organizations[0]["aliases"],
            ["Wheelabrator Group", "Wheelabrator Canada"],
        )


if __name__ == "__main__":
    unittest.main()