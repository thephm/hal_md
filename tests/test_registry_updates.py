import unittest

import extract_interests
import extract_skills


class RegistryUpdateTests(unittest.TestCase):
    def test_skill_merge_preserves_existing_aliases_and_adds_new_spellings(self):
        groups = {"python": ["Python", "Python 3"]}

        extract_skills.merge_skill_groups(groups, ["Python", "PYTHON"])

        self.assertEqual(groups["python"], ["Python", "Python 3", "PYTHON"])

    def test_new_interest_uses_crawler_compatible_aliases_field(self):
        interest = extract_interests.new_interest("play-badminton")

        self.assertEqual(
            interest,
            {"name": "Play Badminton", "slug": "play-badminton", "aliases": []},
        )


if __name__ == "__main__":
    unittest.main()