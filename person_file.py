# Represents a Person Markdown file e.g. "Sponge Bob.md"

# Like all good Markdown files, there's the frontmatter and body.

# The frontmatter fields start with "FIELD_"
# The body has Sections

import os
import sys

sys.path.insert(1, './') 
import md_frontmatter
import md_body
import md_file

# additional tags in a person file
TAG_PERSON = "person"
TAG_ALIST = "alist"
TAG_BLIST = "blist"
TAG_CLIST = "clist"
TAG_DLIST = "dlist"
TAG_ELIST = "elist"
TAG_FLIST = "flist"

Tags = [TAG_PERSON]
OtherTags = [TAG_ALIST, TAG_BLIST, TAG_CLIST, TAG_DLIST, TAG_ELIST, TAG_FLIST]

# fields in a Person file's fronmatter files
FIELD_SUBJECT_ID = "subject_id"
FIELD_FIRST_NAME = "first_name"
FIELD_NICK_NAME = "nick_name"
FIELD_LAST_NAME = "last_name"
FIELD_ALIASES = "aliases"
FIELD_NEE = "nee"

FIELD_SLUG = "slug"
FIELD_GENDER = "gender"
FIELD_PRONOUNS = "pronouns"

FIELD_BIRTHDAY = "birthday"
FIELD_ANNIVERSARY = "anniversary"

FIELD_INTERESTS = "interests"

FIELD_TITLE = "title"
FIELD_ORGANIZATIONS = "organizations"
FIELD_SKILLS = "skills"

FIELD_LAST_CONTACT = "last_contact"
FIELD_LAST_UPDATED = "last_updated"

FIELD_EMAIL = "email"
FIELD_MOBILE = "mobile"
FIELD_PHONE = "phone"
FIELD_URL = "url"

FIELD_WORK_EMAIL = "work_email"
FIELD_WORK_MOBILE = "work_mobile"
FIELD_WORK_PHONE = "work_phone"
FIELD_WORK_URL = "work_url"

FIELD_OTHER_EMAIL = "other_email"
FIELD_OTHER_MOBILE = "other_mobile"
FIELD_OTHER_PHONE = "other_phone"
FIELD_OTHER_URL = "other_url"

FIELD_LINKEDIN_ID = "linkedin_id" 
FIELD_FACEBOOK_ID = "facebook_id"
FIELD_X_ID = "x_id"
FIELD_INSTAGRAM_ID = "instagram_id"
FIELD_MEDIUM_ID = "medium_id"
FIELD_GITHUB_ID = "github_id"
FIELD_SKYPE_ID = "skype_id"

FIELD_HOMETOWN = "hometown"

# not used very often
FIELD_WORK_ADDRESS = "work_address"
FIELD_WORK_CITY = "work_city"
FIELD_WORK_COUNTRY = "work_country"
FIELD_WORK_STATE = "work_state"
FIELD_WORK_ZIP = "work_zip"

FIELD_ADDRESS = "address"
FIELD_CITY = "city"
FIELD_COUNTRY = "country"
FIELD_STATE = "state"
FIELD_ZIP = "zip"

Fields = [md_frontmatter.FIELD_TAGS, FIELD_SUBJECT_ID,
            FIELD_FIRST_NAME, FIELD_LAST_NAME, FIELD_NEE, FIELD_NICK_NAME, 
            FIELD_ALIASES, FIELD_SLUG, FIELD_GENDER, FIELD_PRONOUNS, 
            FIELD_BIRTHDAY, FIELD_ANNIVERSARY, 
            FIELD_TITLE, FIELD_ORGANIZATIONS, 
            FIELD_LAST_CONTACT, FIELD_LAST_UPDATED, 
            FIELD_SKILLS, FIELD_INTERESTS, 
            FIELD_MOBILE, FIELD_EMAIL, FIELD_URL,
            FIELD_WORK_MOBILE, FIELD_WORK_EMAIL, FIELD_WORK_URL,
            FIELD_OTHER_MOBILE, FIELD_OTHER_EMAIL, FIELD_OTHER_URL,
            FIELD_LINKEDIN_ID, FIELD_FACEBOOK_ID, FIELD_X_ID, FIELD_INSTAGRAM_ID, FIELD_MEDIUM_ID, FIELD_GITHUB_ID, FIELD_SKYPE_ID,
            FIELD_HOMETOWN,
            FIELD_ADDRESS, FIELD_CITY, FIELD_STATE, FIELD_COUNTRY, FIELD_ZIP, 
            FIELD_WORK_ADDRESS, FIELD_WORK_CITY, FIELD_WORK_COUNTRY, FIELD_WORK_STATE, FIELD_WORK_ZIP
        ]

# sections of the body
SECTION_BIO = "## Bio"
SECTION_QUOTES = "## Quotes"
SECTION_LIFE_EVENTS = "## Life Events"
SECTION_PEOPLE = "## People"
SECTION_REFERENCES = "## References"
SECTION_FAVORITES = "## Favorites"
SECTION_LIFE_POSITIONS = "## Positions"
SECTION_NOTES = "## Notes"

Sections = [SECTION_BIO, SECTION_QUOTES, SECTION_LIFE_EVENTS, 
            SECTION_REFERENCES, SECTION_PEOPLE, 
            SECTION_FAVORITES, SECTION_NOTES]

class PersonFrontMatter(md_frontmatter.FrontMatter):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.tags.extend(Tags)
        self.fields.extend(Fields)
        self.raw = ""

class PersonBody(md_body.Body):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.sections.extend(Sections)
        self.raw = ""

class PersonFile(md_file.File):
    def __init__(self):
        super().__init__()
        self.frontMatter = PersonFrontMatter(self)
        self.frontMatter.initFields()
        self.body = PersonBody(self)

# -----------------------------------------------------------------------------
#
# Get the list of people slugs based on all of the folder names in `path` but
# not recursively. Each top-level folder contains all of the files for person.
#
# -----------------------------------------------------------------------------
def getSlugs(path):

    slugs = []

    try:
        slugs = [folder for folder in os.listdir(path) if os.path.isdir(os.path.join(path, folder))]
    except:
        pass

    return slugs