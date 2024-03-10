# Represents a Person Markdown file e.g. "Sponge Bob.md"

# Like all good Markdown files, there's the frontmatter and body.

# The frontmatter fields start with "FIELD_"
# The body has Sections

import os
import sys
import glob
import re

sys.path.insert(1, '../hal/')
import person

sys.path.insert(1, './') 
import md_frontmatter
import md_body
import md_file

# sections of the body
SECTION_BIO = "## Bio"
SECTION_QUOTES = "## Quotes"
SECTION_LIFE_EVENTS = "## Life Events"
SECTION_PEOPLE = "## People"
SECTION_REFERENCES = "## References"
SECTION_FAVORITES = "## Favorites"
SECTION_POSITIONS = "## Positions"
SECTION_NOTES = "## Notes"

Sections = [SECTION_BIO, SECTION_QUOTES, SECTION_LIFE_EVENTS, 
            SECTION_REFERENCES, SECTION_PEOPLE, 
            SECTION_FAVORITES, SECTION_NOTES]

class PersonFrontmatter(md_frontmatter.Frontmatter):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.tags.extend(person.Tags)
        self.fields.extend(person.Fields)
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
        self.prefix = ""    # will be the Person's name
        self.frontmatter = PersonFrontmatter(self)
        self.frontmatter.init_fields()
        self.body = PersonBody(self)

# -----------------------------------------------------------------------------
#
# Get the list of people slugs based on all of the folder names in `path` but
# not recursively. Each top-level folder contains all of the files for person.
#
# -----------------------------------------------------------------------------
def get_slugs(path):

    slugs = []

    try:
        # get a list of all folders in the specified path excluding hidden ones
        slugs = [folder for folder in os.listdir(path) 
                 if os.path.isdir(os.path.join(path, folder)) and not folder.startswith('.')]
    except:
        pass

    return slugs

# -----------------------------------------------------------------------------
#
# Update the value of a Person's profile metadata field.
#
# Parameters:
#
#   slug - the person slug, e.g. 'spongebob'
#   path - the path to the file
#   field - the frontmatter field to update, e.g. 'last_contact'
#   value - what to set the field to
#
# Returns:
#
#   A populated Markdown file object.
#
# Notes:
#
#   - Looks for a file that has a tags value `person` and updates the field 
#   - In the case of `last_contact`, it only updates it if it's a more recent
#     date than the current value
#   - @todo: check if yaml.slug == slug to make sure it's the right person
#
# -----------------------------------------------------------------------------
def update(slug, path, field, value):

    result = False

    # get a list of files with ".md" extension
    all_files = glob.glob(os.path.join(path, slug + "/*.md"))

    # pattern for matching YYYY-MM-DD filenames
    date_pattern = re.compile(r'\d{4}-\d{2}-\d{2}')

    # Filter out files with filename format of "YYYY-MM-DD" and those starting with "."
    files = [file for file in all_files if not date_pattern.match(md_file.getPrefix(file))]

    for file in files:
        # load the Person's profile 
        person_file = PersonFile()
        person_file.path = file
        person_file.frontmatter.read()
        yaml = person_file.frontmatter

        # if this is a person's profile file (sounds funny!)
        if yaml.tags and person.TAG_PERSON in yaml.tags:
            try:
                # get the current value of the field
                current_value = getattr(yaml, field)
            except:
                pass  

            # set the `last_contact` if the new value is a more recent date
            if field == person.FIELD_LAST_CONTACT:
                if value > str(current_value):
                    setattr(yaml, field, value)
                    
            # read the body of the file
            person_file.body.read()

            # write the file with the updated 'last_contact' value
            result = person_file.save()

            break

    return result
