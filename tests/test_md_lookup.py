import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import md_lookup


class MarkdownLookupTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        people_folder = Path(self.temp_directory.name)
        person_folder = people_folder / "jane-doe"
        person_folder.mkdir()
        (person_folder / "Jane Doe.md").write_text(
            "---\n"
            "tags: [person]\n"
            "slug: jane-doe\n"
            "first_name: Jane\n"
            "email: jane@example.com\n"
            "mobile: 555-0100\n"
            "---\n",
            encoding="utf-8",
        )
        self.people_folder = str(people_folder)
        self.arguments = SimpleNamespace(debug=False, max=10)

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_gets_nested_contact_fields(self):
        values = md_lookup.get_values(
            self.people_folder, ["email", "mobile"], self.arguments
        )

        self.assertEqual(values[0]["email"], "jane@example.com")
        self.assertEqual(values[0]["mobile"], "555-0100")

    def test_no_fields_gets_all_populated_frontmatter_fields(self):
        values = md_lookup.get_values(self.people_folder, [], self.arguments)

        self.assertEqual(values[0]["first_name"], "Jane")
        self.assertEqual(values[0]["email"], "jane@example.com")
        self.assertEqual(values[0]["mobile"], "555-0100")
        self.assertNotIn("last_contact", values[0])


if __name__ == "__main__":
    unittest.main()