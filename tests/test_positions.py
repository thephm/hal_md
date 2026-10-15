import unittest

from hal_md.positions import (
    format_timeline_description,
    merge_timeline_sections,
    sort_timeline_items,
    timeline_date_range,
)


class TimelineTests(unittest.TestCase):
    def test_end_date_takes_precedence_over_current_flag(self):
        self.assertEqual(
            timeline_date_range(
                {"start_date": "2020-01-01", "end_date": "2022-02-01", "current": True}
            ),
            "2020-01-01 to 2022-02-01",
        )

    def test_sort_places_undated_then_completed_then_current_items(self):
        items = [
            {"title": "Current", "start_date": "2023", "current": True},
            {"title": "Completed later", "start_date": "2021", "end_date": "2022"},
            {"title": "Undated"},
            {"title": "Completed earlier", "start_date": "2018", "end_date": "2020"},
        ]
        self.assertEqual(
            [item["title"] for item in sort_timeline_items(items)],
            ["Undated", "Completed earlier", "Completed later", "Current"],
        )

    def test_bulleted_descriptions_are_flattened(self):
        self.assertEqual(
            format_timeline_description("- Managed the team.\n- Delivered the project."),
            "  > Managed the team. Delivered the project.",
        )

    def test_merge_removes_current_suffix_from_ended_existing_entry(self):
        existing = (
            "# Person\n\n## Positions\n\n"
            "- Developer, [[Example Corp]], [[London]], 2019 to 2021 #current\n\n"
            "## People\n"
        )
        generated = (
            "# Person\n\n## Positions\n\n"
            "- Developer, [[Example Corp]], [[London]], 2019 to 2021\n\n"
            "## People\n"
        )

        merged = merge_timeline_sections(existing, generated)

        self.assertEqual(merged.count("- Developer,"), 1)
        self.assertIn("- Developer, [[Example Corp]], [[London]], 2019 to 2021", merged)
        self.assertNotIn("2021 #current", merged)


if __name__ == "__main__":
    unittest.main()
