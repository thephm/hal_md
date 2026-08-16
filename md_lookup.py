# Retrieve a specific attribute for collection of people

import os
import glob
import json
import re
from argparse import ArgumentParser

import sys

sys.path.insert(1, '../hal/') 
import person
import identity

sys.path.insert(1, './') 
import md_person
import md_file

FIELD_VALUES = "values"

# Support both older `hal` modules that exported field constants and newer
# modules that only define classes.
PERSON_TAG_FIELD = getattr(person, "tag", "person")
PERSON_SLUG_FIELD = getattr(person, "slug", "slug")
PERSON_NAME_FIELD = getattr(identity, "name", "name")

def get_arguments():
    parser = ArgumentParser(
        description="Retrieve frontmatter attributes from Person Markdown files."
    )

    parser.add_argument("-f", "--folder", dest="folder", default=".",
                        help="The folder where each Person has a subfolder named with their slug")

    parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False,
                        help="Print extra info as the files are processed")

    parser.add_argument("-x", "--max", type=int, dest="max", default=99999,
                        help="Maximum number of people to process")

    parser.add_argument("fields", metavar="FIELD", nargs="*",
                        help="Frontmatter field(s) to retrieve; omit to retrieve all fields")

    return parser.parse_args()

def get_values(folder, fields, args):
    """
    Given a folder name, get a specific set of attribute for each person under 
    that folder.

    Arguments:
    folder (str): Source folder containing sub-folders for each person
    fields (list): The attributes in the frontmatter to retrieve
    args (list): Arguments including maximum number of people to load

    Returns:
    list: collection of {name, slug, value}
    """

    if args.debug:
        print("get_values('" + folder + "', " + "'" + str(fields) + "', " + str(args) + ")")

    values = []

    # get list of people `slug`s from the folder names
    slugs = md_person.get_slugs(folder)

    count = 0

    # for each person get the values for the fields
    for slug in slugs:
        person_values = get_person_values(folder, slug, fields)

        # check if at least one requested field (or any profile field) is non-empty
        result_fields = fields or [
            field for field in person_values
            if field not in (PERSON_SLUG_FIELD, PERSON_NAME_FIELD)
        ]
        has_non_empty_field = any(person_values.get(field) for field in result_fields)

        # only add those people where there was a value found
        if has_non_empty_field:
            if args.debug:
                print(str(person_values))
            values.append(person_values)
            count += 1
        if count >= args.max:
            break

    return values

def get_person_values(folder, slug, fields):
    """
    Get a specific person's attributes from the frontmatter in their profile.

    Parameters:
    folder (str): Source folder containing sub-folders for each person
    slug (str): Slug of the person 
    fields (list): The frontmatter fields to read, e.g. {'birthday', 'deathday'}

    Returns:
    list: {fileprefix, value} of the field, file_prefix will be the person's name
    """

    result = {}

    path = os.path.join(folder, slug)

    # get a list of files with ".md" extension
    all_files = glob.glob(os.path.join(path, "*.md"))

    # pattern for matching YYYY-MM-DD filenames
    date_pattern = re.compile(r'\d{4}-\d{2}-\d{2}')

    # Filter out files with filename format of "YYYY-MM-DD"
    files = [file for file in all_files if os.path.isfile(file) and not date_pattern.match(md_file.get_prefix(file))]

    for file in files:
        theFile = md_person.PersonFile()
        theFile.path = file
        theFile.frontmatter.read()
        if theFile.file:
            theFile.file.close()
            theFile.file = None
        yaml = theFile.frontmatter
        
        # if this is a person profile and the right person 
        if yaml.tags and PERSON_TAG_FIELD in yaml.tags:
            # for each of the fields being requested
            result[PERSON_SLUG_FIELD] = slug
            result[PERSON_NAME_FIELD] = md_file.get_prefix(file)
            selected_fields = fields or yaml.fields
            for field in selected_fields:
                source_field = "tags" if field == "tag" else field
                value = get_field_value(theFile, source_field)
                if fields or value not in (None, "", []):
                    result[field] = "" if value is None else str(value)

    return result

def get_field_value(person_file, field):
    """Return a flat frontmatter field from its mapped PersonFile location."""
    path = md_person.YAML_TO_ATTR.get(field)
    if path:
        value = person_file
        for attribute in path:
            if attribute:
                value = getattr(value, attribute, None)
            if value is None:
                break
        return value

    return getattr(person_file, field, None)

if __name__ == "__main__":
    arguments = get_arguments()
    print(json.dumps(get_values(arguments.folder, arguments.fields, arguments), indent=2))