# Retrieve a specific attribute for collection of people

import os
import glob
import re

import sys

sys.path.insert(1, '../hal/') 
import person
import identity

sys.path.insert(1, './') 
import md_person
import md_file

FIELD_VALUES = "values"

# -----------------------------------------------------------------------------
#
# Given a folder name, get a specific set of attribute for each person under 
# that folder.
#
# Parameters:
# 
#   - folder - source folder containing sub-folders for each person
#   - fields - the attributes in the frontmatter  tp retrieve
#   - max - maximum number of people to load
#
# Returns:
#
#   - collection of {name, slug, value}
#
# Notes:
#
# -----------------------------------------------------------------------------
def get_values(folder, fields, args):

    if args.debug:
        print("get_values('" + folder + "', " + "'" + str(fields) + "', " + str(args) + ")")

    values = []

    # get list of people `slug`s from the folder names
    slugs = md_person.get_slugs(folder)

    count = 0

    # for each person get the values for the fields
    for slug in slugs:
        person_values = get_person_values(folder, slug, fields)

        # check if at least one of the fields requested is non-empty
        has_non_empty_field = any(person_values.get(field) for field in fields)

        # only add those people where there was a value found
        if has_non_empty_field:
            if args.debug:
                print(str(person_values))
            values.append(person_values)
            count += 1
        if count >= args.max:
            break

    return values

# -----------------------------------------------------------------------------
#
# Get a specific person's attributes from the frontmatter in their profile.
#
# Parameters:
#
#   folder - source folder containing sub-folders for each person
#   slug - slug of the person 
#   fields - the frontmatter fields to read, e.g. {'birthday', 'deathday'}
#
# Returns:
#
#   {fileprefix, value} of the field, file_prefix will be the person's name
#
# -----------------------------------------------------------------------------
def get_person_values(folder, slug, fields):

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
        yaml = theFile.frontmatter
        
        # if this is a person profile and the right person 
        if yaml.tags and person.TAG_PERSON in yaml.tags:
            # for each of the fields being requested
            result[person.FIELD_SLUG] = slug
            result[identity.FIELD_NAME] = md_file.get_prefix(file)
            for field in fields:
                result[field] = ""
                try:
                    # get the value of the field
                    value = getattr(yaml, field)
                    if value is not None:
                        result[field] = str(value)
                except:
                    pass  # it's ok not to have the field

    return result