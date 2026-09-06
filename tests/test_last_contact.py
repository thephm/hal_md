import datetime as dt
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools.last_contact import update_last_contact


class LastContactTests(unittest.TestCase):
    def test_does_not_overwrite_a_more_recent_manual_last_contact(self):
        interactions = [SimpleNamespace(slug="jane-doe", date=dt.date(2026, 9, 1))]
        person_file = SimpleNamespace(last_contact=dt.date(2026, 9, 4))

        with patch("tools.last_contact.md_person.read_person_frontmatter", return_value=person_file), patch(
            "tools.last_contact.md_person.update_field"
        ) as update_field:
            result = update_last_contact("people", interactions)

        self.assertFalse(result)
        update_field.assert_not_called()

    def test_updates_when_latest_dated_file_is_newer(self):
        interactions = [SimpleNamespace(slug="jane-doe", date=dt.date(2026, 9, 5))]
        person_file = SimpleNamespace(last_contact="2026-09-04")

        with patch("tools.last_contact.md_person.read_person_frontmatter", return_value=person_file), patch(
            "tools.last_contact.md_person.update_field", return_value=True
        ) as update_field:
            result = update_last_contact("people", interactions)

        self.assertTrue(result)
        update_field.assert_called_once_with("jane-doe", "people", "last_contact", "2026-09-05")


if __name__ == "__main__":
    unittest.main()