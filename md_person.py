# Represents a Person Markdown file e.g. "Sponge Bob.md"

# Like all good Markdown files, there's the frontmatter and body.

# The frontmatter fields start with "FIELD_"
# The body has Sections

import os
import sys
import glob
import re
import yaml

sys.path.insert(1, '../hal/')
import person
import identity
import contact
import socials

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
    
# flat YAML key -> (object path as tuple)
YAML_TO_ATTR = {
    "tags": ("", "tags"),
    "slug": ("", "slug"),
    "subject_id": ("", "subject_id"),
    "connected_on": ("", "connected_on"),
    "birthday": ("", "birthday"),
    "deathday": ("", "deathday"),
    "anniversary": ("", "anniversary"),
    "interests": ("", "interests"),
    "favorites": ("", "favorites"),
    "service_id": ("", "service_id"),
    "title": ("", "title"),
    "organizations": ("", "organizations"),
    "positions": ("", "positions"),
    "skills": ("", "skills"),
    "first_name": ("identity", "first_name"),
    "middle_name": ("identity", "middle_name"),
    "last_name": ("identity", "last_name"),
    "nick_name": ("identity", "nick_name"),
    "nee": ("identity", "nee"),
    "gender": ("identity", "gender"),
    "pronouns": ("identity", "pronouns"),
    "aliases": ("identity", "aliases"),
    "mobile": ("contact", "mobile"),
    "last_contact": ("", "last_contact"),
    "phone": ("contact", "phone"),
    "email": ("contact", "email"),
    "url": ("contact", "url"),
    "work_mobile": ("work_contact", "mobile"),
    "work_email": ("work_contact", "email"),
    "work_url": ("work_contact", "url"),
    "other_mobile": ("other_contact", "mobile"),
    "other_email": ("other_contact", "email"),
    "other_url": ("other_contact", "url"),
    "linkedin_id": ("socials", "linkedin_id"),
    "facebook_id": ("socials", "facebook_id"),
    "instagram_id": ("socials", "instagram_id"),
    "bluesky_id": ("socials", "bluesky_id"),
    "x_id": ("socials", "x_id"),
    "github_id": ("socials", "github_id"),
    "medium_id": ("socials", "medium_id"),
    "threads_id": ("socials", "threads_id"),
    "address": ("contact", "address", "address"),
    "city": ("contact", "address", "city"),
    "province": ("contact", "address", "province"),
    "country": ("contact", "address", "country"),
    "hometown": ("contact", "address", "hometown"),
}

class PersonFrontmatter(md_frontmatter.Frontmatter):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.tags.extend(person.Tags)
        self.fields.extend(person.Fields)
        self.section_headings = PersonSections
        self.raw = ""
    
    def parse(self):
        """
        Parse the YAML frontmatter into fields and assign to embedded objects.
        """
        result = False
        try:
            yamlData = yaml.safe_load_all(self.raw)
            for doc in yamlData:
                if isinstance(doc, dict):
                    # preserve the order and all fields
                    self.fields = list(doc.keys())
                    for key, value in doc.items():
                        if key == "tags":
                            self.tags = value  
                            self.parent.tags = value 
                        if key in YAML_TO_ATTR:
                            obj = self.parent
                            path = YAML_TO_ATTR[key]
                            for attr in path[:-1]:
                                if attr:  # Only traverse if attr is not empty
                                    obj = getattr(obj, attr, None)
                                    if obj is None:
                                        break
                            if obj is not None:
                                setattr(obj, path[-1], value)
                        else:
                            setattr(self.parent, key, value)
                    result = True
        except Exception as e:
            print(e)
        return result

class PersonBody(md_body.Body):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.sections = []
        self.raw = ""

class PersonFile(md_file.File):
    def __init__(self):
        super().__init__()
        self.prefix = ""
        self.subject_id = ""
        self.slug = ""
        self.connected_on = ""
        self.birthday = ""
        self.deathday = ""
        self.anniversary = ""
        self.interests = []
        self.favorites = []
        self.title = ""
        self.organizations = []
        self.skills = []
        self.last_contact = ""
        self.last_updated = ""
        self.identity = identity.Identity()
        self.contact = contact.Contact()
        self.contact.qualifier = contact.QUALIFIER_HOME
        self.work_contact = contact.Contact()
        self.work_contact.qualifier = contact.QUALIFIER_WORK
        self.other_contact = contact.Contact()
        self.other_contact.qualifier = contact.QUALIFIER_OTHER
        self.socials = socials.Socials()
        self.frontmatter = PersonFrontmatter(self)
        self.frontmatter.init_fields()
        self.body = PersonBody(self)
        
    def get_yaml(self):
        result = md_frontmatter.FRONTMATTER_SEPARATOR + NEW_LINE

        for field in self.frontmatter.fields:
            if field in YAML_TO_ATTR:
                obj = self
                path = YAML_TO_ATTR[field]
                for attr in path[:-1]:
                    if attr:
                        obj = getattr(obj, attr, None)
                        if obj is None:
                            break
                if obj is not None:
                    value = getattr(obj, path[-1], None)
                else:
                    value = None
            else:
                value = getattr(self, field, None)

            if value not in (None, "", []):
                result += f"{field}: {value}\n"

        result += md_frontmatter.FRONTMATTER_SEPARATOR + NEW_LINE

        return result

    def section_top(self, section, before):
        """
        Get the first part of a section of the body.

        Parameters:
        section (str): The name of the section e.g. "## Notes"
        before (str): Get any content before this text

        Returns:
        str: The first part of the section.

        Notes:
        - Looks for any content in the section in front of the 'before' text
        - Useful to get notes before the first embedded wikilink in "## Notes"
          so it can be retained 

        - Example: if before is "![[spongebob/2024-03-24.md]]", it will find:
            "![[spongebob/2024-03-24.md]]"          # nothing before
            "- ![[spongebob/2024-03-24.md]]"        # bullet before
            "   - ![[spongebob/2024-03-24.md]]"     # tabs before "-"
            "-  ![[spongebob/2024-03-24.md]]"       # tabs after "-"
        """

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

    def update_section(self, slug, section_heading, value):
        """
        Update a specific section within a Person's profile Markdown file body.
        
        Parameters:
        slug (str): The person's slug, e.g. 'spongebob'
        section_heading (str): The body section to update e.g. SECTION_NOTES
        value (str): What to set the field to.

        Returns:
        bool: True if saved, false if not.

        Notes:
        The section header should have a blank line before and after it
        """

        result = False

        if self.file is not None:

            # this also parses it
            self.body.read()

            # check if the section exists in the file
            for section in self.body.sections:
                if section['heading'] == section_heading:
                    # update the content of the section
                    section['content'] = value

            # write the file with the updated section
            result = self.save()

        return result
    
    def save(self):
        """
        Save the PersonFile, writing the correct YAML frontmatter and body.
        """
        # Open file for writing
        if self.file:
            self.file.close()
        self.open('w+')

        # Write the YAML frontmatter using the custom get_yaml()
        self.file.write(self.get_yaml())

        # Write the body (if you want to preserve the rest of the file)
        if hasattr(self.body, "get_text"):
            self.file.write(self.body.get_text())
        else:
            # fallback: just write the raw body if available
            if hasattr(self.body, "raw"):
                self.file.write(self.body.raw)

        self.file.truncate()  # Remove any leftover content if file shrank
        self.file.flush()
        return True

def get_slugs(path):
    """
    Get a list of people slugs based on the folder names under `path`.

    Parameters:
    path (str): The path to the file
    
    Returns:
    list: slugs

    Notes:
    - Each top-level folder contains all of the files for person
    - Does not recursively
    """

    slugs = []

    try:
        # get a list of all folders in the specified path excluding hidden ones
        slugs = [folder for folder in os.listdir(path) 
                 if os.path.isdir(os.path.join(path, folder)) and not folder.startswith('.')]
    except:
        pass

    return slugs

def get_non_dated_files(slug, path):
    """
    Get a list of a person's Markdown files not named with `YYYY-MM-DD`.

    Parameters:
    slug (str): The person slug, e.g. 'spongebob'
    path (str): The path to the file

    Returns:
    list: A list of files.
    """

    # get a list of files with ".md" extension
    all_files = glob.glob(os.path.join(path, slug + "/*.md"))

    # pattern for matching filenames starting with YYYY-MM-DD [#12]
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}.*')

    # filter out files with filename format of "YYYY-MM-DD" and those starting with "."
    files = [file for file in all_files if not date_pattern.match(md_file.get_prefix(file))]

    return files

def read_person_frontmatter(slug, path):
    """
    Figure out which file from a list of filenames is the Person's profile.

    Parameters:
    slug (str): The person slug, e.g. 'spongebob'.
    path (str): The path to the file.

    Returns:
    PersonFile: The first file found with `tags: [person]` in it or None.
    """
    
    # get list of files that aren't interactions or notes e.g. ! `2024-03-22.md`
    files = get_non_dated_files(slug, path)

    for file in files:
        # load the file assuming it's a Person file
        person_file = PersonFile()
        person_file.path = file
        person_file.frontmatter.read()

        frontmatter = person_file.frontmatter

        # check if it actually is this person's profile 
        if frontmatter.tags and person.TAG_PERSON in frontmatter.tags:
            return person_file

    return None

def update_field(slug, path, field, value):
    """
    Update the value of a Person's specific profile metadata field.
    """
    result = False

    # get the Person's profile file
    person_file = read_person_frontmatter(slug, path)

    if person_file is not None:
        yaml = person_file.frontmatter

        # read the body of the file (this also parses frontmatter)
        person_file.body.read()

        # use YAML_TO_ATTR to set the value in the correct place
        if field in YAML_TO_ATTR:
            obj = person_file
            path_tuple = YAML_TO_ATTR[field]
            for attr in path_tuple[:-1]:
                if attr:
                    obj = getattr(obj, attr, None)
                    if obj is None:
                        break
            if obj is not None:
                setattr(obj, path_tuple[-1], value)
        else:
            setattr(person_file, field, value)

        # write the file with the updated value
        result = person_file.save()

    return result