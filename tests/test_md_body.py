import unittest

from md_body import Body


class BodyTests(unittest.TestCase):
    def test_get_text_normalizes_heading_spacing(self):
        body = Body(parent=None)
        body.sections = [
            {"heading": "# Jane Doe", "content": "Bio"},
            {"heading": "## Notes", "content": "A note\n\n\n"},
        ]

        self.assertEqual(
            body.get_text(),
            "\n# Jane Doe\n\nBio\n\n## Notes\n\nA note\n\n",
        )


if __name__ == "__main__":
    unittest.main()