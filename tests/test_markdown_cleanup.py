import unittest

from markdown_cleanup import normalize_heading_spacing


class MarkdownCleanupTests(unittest.TestCase):
    def test_normalizes_spacing_around_level_two_and_three_headings(self):
        source = "---\ntitle: Example\n---\n## First\nText\n\n\n### Second\nMore text\n"

        self.assertEqual(
            normalize_heading_spacing(source),
            "---\ntitle: Example\n---\n\n## First\n\nText\n\n### Second\n\nMore text\n",
        )

    def test_preserves_frontmatter_and_fenced_code(self):
        source = "---\ntitle: ## Keep\n---\n```markdown\n## Code\nText\n```\n## Heading\nText\n"

        self.assertEqual(
            normalize_heading_spacing(source),
            "---\ntitle: ## Keep\n---\n```markdown\n## Code\nText\n```\n\n## Heading\n\nText\n",
        )

    def test_is_idempotent(self):
        source = "## Heading\n\nText\n"

        self.assertEqual(normalize_heading_spacing(source), source)


if __name__ == "__main__":
    unittest.main()
