import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "message_md"))

from config import Config


def test_get_or_create_person_adds_signal_contact_and_saves_people(tmp_path):
    config = Config()
    config.config_folder = str(tmp_path)
    config.people = []
    config.create_people = True
    config.output_folder = str(tmp_path / "output")
    config.people_subfolder = "People"
    config.people_folder = str(config.output_folder / config.people_subfolder)

    with patch("builtins.input", return_value="a"):
        person = config.get_or_create_person(
            full_name="Jane Doe",
            mobile="+1 555 123 4567",
            source="Signal",
            conversation_id="abc-123",
        )

    assert person is not None
    assert person.slug == "jane-doe"
    assert person.identity.first_name == "Jane"
    assert person.identity.last_name == "Doe"
    assert person.contact.mobile == "15551234567"
    assert person.conversation_id == "abc-123"

    saved = json.loads((tmp_path / "people.json").read_text(encoding="utf-8"))
    assert saved[0]["slug"] == "jane-doe"
    assert saved[0]["first_name"] == "Jane"
    assert saved[0]["last_name"] == "Doe"
    assert saved[0]["mobile"] == "15551234567"


def test_write_person_markdown_template_includes_linkedin_reference_and_note(tmp_path):
    config = Config()
    config.output_folder = str(tmp_path / "output")
    config.people_subfolder = "People"
    config.people_folder = str(config.output_folder / config.people_subfolder)

    person = config.get_or_create_person(
        full_name="Jane Doe",
        linkedin_id="jane-doe",
        source="LinkedIn",
        prompt=False,
    )

    file_path = config.write_person_markdown_template(person, source="LinkedIn")

    content = Path(file_path).read_text(encoding="utf-8")
    assert "linkedin_id: jane-doe" in content
    assert "1. [LinkedIn](https://www.linkedin.com/in/jane-doe)" in content
    assert "added from LinkedIn" in content
