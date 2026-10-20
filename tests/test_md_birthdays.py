import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "tools" / "md_birthdays.py"


class BirthdayCommandTests(unittest.TestCase):
    def run_command(self, cwd, *arguments):
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_help_from_different_working_directories(self):
        with tempfile.TemporaryDirectory() as unrelated_directory:
            for cwd in (
                REPOSITORY_ROOT,
                REPOSITORY_ROOT / "tools",
                unrelated_directory,
            ):
                with self.subTest(cwd=cwd):
                    result = self.run_command(cwd, "--help")

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("--upcoming", result.stdout)

    def test_calendar_from_tools_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            person_folder = Path(directory) / "jane-doe"
            person_folder.mkdir()
            (person_folder / "Jane Doe.md").write_text(
                "---\n"
                "tags: [person]\n"
                "slug: jane-doe\n"
                "birthday: '05-14'\n"
                "---\n",
                encoding="utf-8",
            )

            result = self.run_command(
                REPOSITORY_ROOT / "tools", "--folder", directory
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("## May", result.stdout)
            self.assertIn("14 | [[Jane Doe]] |  | ", result.stdout)


if __name__ == "__main__":
    unittest.main()
