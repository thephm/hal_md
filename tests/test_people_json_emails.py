import unittest

from compare_and_update_json import normalize_email_fields
from create_people_json import extract_emails, extract_person_info


class PeopleJsonEmailsTests(unittest.TestCase):
    def test_create_people_json_extracts_emails_as_list(self):
        frontmatter = {
            "email": "first@example.com;second@example.com",
            "work_email": "second@example.com",
            "other_email": "other@example.com",
        }

        self.assertEqual(extract_emails(frontmatter), ["first@example.com", "second@example.com", "other@example.com"])

    def test_create_people_json_writes_emails_not_email(self):
        person = extract_person_info(
            {
                "tags": ["person"],
                "slug": "jane-doe",
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "jane@example.com",
            },
            "jane-doe",
            "unused.md",
        )

        self.assertEqual(person["emails"], ["jane@example.com"])
        self.assertNotIn("email", person)

    def test_compare_update_normalizes_legacy_email_to_emails(self):
        normalized = normalize_email_fields(
            {
                "slug": "jane-doe",
                "email": "first@example.com;second@example.com",
                "emails": ["second@example.com", "third@example.com"],
            }
        )

        self.assertEqual(normalized["emails"], ["first@example.com", "second@example.com", "third@example.com"])
        self.assertNotIn("email", normalized)


if __name__ == "__main__":
    unittest.main()
