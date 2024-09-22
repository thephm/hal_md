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
NEW_LINE = "\n"
SECTION_H1 = "# "
SECTION_BIO = "## Bio"
SECTION_QUOTES = "## Quotes"
SECTION_LIFE_EVENTS = "## Life Events"
SECTION_PEOPLE = "## People"
SECTION_REFERENCES = "## References"
SECTION_FAVORITES = "## Favorites"
SECTION_POSITIONS = "## Positions"
SECTION_NOTES = "## Notes"
CONTENT_EMBED = "![["

PersonSections = [SECTION_BIO, SECTION_QUOTES, SECTION_LIFE_EVENTS, 
                  SECTION_REFERENCES, SECTION_PEOPLE, SECTION_FAVORITES, 
                  SECTION_NOTES]

class PersonFrontmatter(md_frontmatter.Frontmatter):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.tags.extend(person.Tags)
        self.fields.extend(person.Fields)
        self.section_headings = PersonSections
        self.raw = ""

class PersonBody(md_body.Body):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.sections = []
        self.raw = ""

class PersonFile(md_file.File):
    def __init__(self):
        super().__init__()
        self.prefix = ""    # will be the Person's name
        self.frontmatter = PersonFrontmatter(self)
        self.frontmatter.init_fields()
        self.body = PersonBody(self)

    # -------------------------------------------------------------------------
    #
    # Get the first part of a section of the body.
    #
    # Parameters:
    #
    #   - section - the name of the section e.g. "## Notes"
    #   - before - get any content before this text
    #
    # Returns:
    #
    #   - The first part of the section
    #
    # Notes:
    #
    #   - Looks for any content in the section in front of the 'before' text
    #
    #   - Useful to get notes before the first embedded wikilink in "## Notes"
    #     so it can be retained 
    #
    #   - Example: if before is "![[spongebob/2024-03-24.md]]", it will find:
    #
    #       "![[spongebob/2024-03-24.md]]"          # nothing before
    #       "- ![[spongebob/2024-03-24.md]]"        # bullet before
    #       "   - ![[spongebob/2024-03-24.md]]"     # tabs before "-"
    #       "-  ![[spongebob/2024-03-24.md]]"       # tabs after "-"
    #    
    # -------------------------------------------------------------------------
    def section_top(self, section, before):

        top = ""
        
        # read the body of the file, which also parses it
        self.body.read()

        if self.file is not None:

            # get the current content of the "## Notes" section
            content = self.body.get_content(section)

            if content is not None:
                for line in content.split(NEW_LINE):
                    # if it's not a lines that starts with "before" text, add it
                    if before not in line:
                        top += line + NEW_LINE
                    else:
                        break

        return top

    # -------------------------------------------------------------------------
    #
    # Update a specific section within a Person's profile Markdown file body.
    #
    # Parameters:
    #
    #   slug - the person slug, e.g. 'spongebob'
    #   section_heading - the body section to update e.g. SECTION_NOTES
    #   value - what to set the field to
    #
    # Returns:
    #
    #   True if successful, False otherwise.
    #
    # Notes:
    #
    #   - The section header should have a blank line before and after it
    #
    # -------------------------------------------------------------------------
    def update_section(self, slug, section_heading, value):

        result = False

        # get the Person's profile file
        # person_file = read_person_frontmatter(slug, path)

        if self.file is not None:

            # read the body of the file, which also parses it
            self.body.read()

            # check if the section exists in the file
            for section in self.body.sections:
                if section['heading'] == section_heading:
                    # update the content of the section
                    section['content'] = value

            # write the file with the updated section
            result = self.save()

        return result

# -------------------------------------------------------------------------
#
# Get a list of people slugs based on the folder names under `path`.
#
# Parameters:
#
#   path - the path to the file
#
# Notes:
#
#   - Each top-level folder contains all of the files for person
#   - Does not recursively
#
# -------------------------------------------------------------------------
def get_slugs(path):

    slugs = []

    try:
        # get a list of all folders in the specified path excluding hidden ones
        slugs = [folder for folder in os.listdir(path) 
                 if os.path.isdir(os.path.join(path, folder)) and not folder.startswith('.')]
    except:
        pass

    return slugs

# -------------------------------------------------------------------------
#
# Get a list of a person's Markdown files not named with `YYYY-MM-DD`.
# 
# Parameters:
#
#   slug - the person slug, e.g. 'spongebob'
#   path - the path to the file
#
# Returns:
#
#   A list of files.
#
# -------------------------------------------------------------------------
def get_non_dated_files(slug, path):

    # get a list of files with ".md" extension
    all_files = glob.glob(os.path.join(path, slug + "/*.md"))

    # pattern for matching YYYY-MM-DD filenames
    date_pattern = re.compile(r'\d{4}-\d{2}-\d{2}')

    # filter out files with filename format of "YYYY-MM-DD" and those starting with "."
    files = [file for file in all_files if not date_pattern.match(md_file.get_prefix(file))]

    return files

# -------------------------------------------------------------------------
#
# Figure out which file from a list of filenames is the Person's profile.
# 
# Parameters:
#
#   slug - the person slug, e.g. 'spongebob'
#   path - the path to the file
#
# Returns:
#
#   The first file found with `tags: [person]` in it or None.
#
# -------------------------------------------------------------------------
def read_person_frontmatter(slug, path):
    
    # get list of files that aren't interactions or notes e.g. ! `2024-03-22.md`
    files = get_non_dated_files(slug, path)

    for file in files:
        # load the file assuming it's a Person file
        person_file = PersonFile()
        person_file.path = file
        person_file.frontmatter.read()
        
        yaml = person_file.frontmatter

        # check if it actually is this person's profile 
        if yaml.tags and person.TAG_PERSON in yaml.tags:
            return person_file

    return None

# -------------------------------------------------------------------------
#
# Update the value of a Person's specific profile metadata field.
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
#   True if successful, False otherwise.
#
# Notes:
#
#   - In the case of `last_contact`, only update it if it's a more recent
#     date than the current value
#   - @todo: check if yaml.slug == slug to make sure it's the right person
#
# -------------------------------------------------------------------------
def update_field(slug, path, field, value):

    result = False

    # get the Person's profile file
    person_file = read_person_frontmatter(slug, path)

    if person_file is not None:

        yaml = person_file.frontmatter

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

    return result
