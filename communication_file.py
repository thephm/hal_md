# Represents a Markdown file containing communications like email or chat.

import sys
sys.path.insert(1, './') 
import md_frontmatter
import md_body
import md_file

# communication tags
TAG_CHAT = "chat"
TAG_EMAIL = "email"
TAG_PHONE = "phone"
TAG_CALL = "call"

Tags = [TAG_CHAT, TAG_EMAIL, TAG_PHONE, TAG_CALL]

# fields in a communication Markdown files
FIELD_PEOPLE = "people"
FIELD_SERVICE = "service"
FIELD_TOPIC = "topic"
FIELD_DATE = "date"
FIELD_TIME = "time"

Fields = [FIELD_PEOPLE, FIELD_TOPIC, FIELD_DATE, FIELD_TIME, FIELD_SERVICE]

class CommunicationFrontmatter(md_frontmatter.Frontmatter):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.tags.extend(Tags)
        self.fields.extend(Fields)
        self.raw = ""

class CommunicationBody(md_body.Body):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.raw = ""

class CommunicationFile(md_file.File):
    def __init__(self):
        super().__init__()
        self.frontmatter = CommunicationFrontmatter(self)
        self.frontmatter.init_fields()
        self.body = CommunicationBody(self)
