import unittest

import yaml

import extract_organizations as eo


class ExtractOrganizationsTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()