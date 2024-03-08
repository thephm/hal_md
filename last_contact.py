# Updates the "last_contact" frontmatter field based on atomic dated files.     

import os
import glob
from argparse import ArgumentParser

import sys
sys.path.insert(1, './') 
import person_file
import interaction

# Parse the command line arguments
def getArguments():

    parser = ArgumentParser()

    parser.add_argument("-f", "--folder", dest="folder", default=".",
                        help="The folder where each Person has a subfolder named with their slug")
    
    parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False,
                        help="Print extra info as the files processed")
    
    parser.add_argument("-t", "--template", dest="template", default=0,
                        help="Markdown template file")
    
    parser.add_argument("-x", "--max", dest="max", default=0,
                        help="Maximum number of people to process")
    
    args = parser.parse_args()

    return args

# -----------------------------------------------------------------------------
#
# Given a folder name, find all of the interactions with that person based on
# the existence of dated Markdown files for each date where an interaction 
# occured.
#
# Parameters:
# 
#   - folder - folder containing sub-folders for each person
#   - interactions - collection of Interaction
#
# Returns:
#
#   - the number of interactions
#
# Notes:
# 
#   - #todo maybe use `Message` `from message_md` instead of `Interaction`
#   - as go through the files, e.g. exclude "tags: note" 
#
# -----------------------------------------------------------------------------
def parsePeople(folder, interactions):

    # get list of people `slug`s from the folder names
    slugs = person_file.getSlugs(folder)

    count = 0

    # for each person find the most recent communication
    for slug in slugs:
        interactions = []
        theDate = ""

        # get the `last_contact` date for the person
        theDate = interaction.getInteractions(slug, os.path.join(folder, slug), interactions)

        # sort the interactions by reverse date and take the first one
        interactions.sort(key=lambda x: x.date, reverse=True)

        # find their profile and update it
        if theDate:
            update(slug, folder, person_file.FIELD_LAST_CONTACT, str(theDate))

        if args.debug:
            print(slug + ": " + str(theDate))
        else:
            print(slug + ": " + str(theDate) + " "*20,  end="\r")

        if args.max and count >= int(args.max): 
            return count
        
        count += 1
    
    return count

# -----------------------------------------------------------------------------
#
# Update a Person's profile with the `last_contact` date.
#
# Parameters:
#
#   slug - the person slug, e.g. 'spongebob'
#   path - the path to the file
#   field - the frontmatter field to update, e.g. 'last_contact'
#   file - the filename without '.md' extension, e.g. "Spongebob Squarepants"
#   value - what to set the field to
#
# Returns:
#
#   A populated Markdown file object.
#
# Notes:
#
#   Checks for a file that has a tags value `person` and updates the last 
#   contact date unless it's already set to a more recent value.
#
# -----------------------------------------------------------------------------
def update(slug, path, field, value):

    lastContact = None

    # get a list of files with ".md" extension
    files = glob.glob(os.path.join(path, slug + "/*.md"))

    for file in files:
        personFile = person_file.PersonFile()
        personFile.path = file
        personFile.frontMatter.read()
        yaml = personFile.frontMatter
        
        # @todo: check if yaml.slug == slug to make sure it's
        # the right person. Not everyone has that field yet.

        # if this is a person profile and the right person 
        if yaml.tags and person_file.TAG_PERSON in yaml.tags:
            if field == person_file.FIELD_LAST_CONTACT:
                try:
                    lastContact = getattr(yaml, field)
                except:
                    pass  # it's ok not to have the field as it was added 

                if value > str(lastContact):
                    setattr(yaml, field, value)
                    
                    # read the body of the file
                    personFile.body.read()

                    # write the file with the updated 'last_contact' value
                    personFile.save()
                    break

    return personFile

# main

args = getArguments()
interactions = []

if args.folder and not os.path.exists(args.folder):
    print('The folder "' + args.folder + '" could not be found.')

elif args.folder:
    count = parsePeople(args.folder, interactions)

    print(str(count) + " people checked" + " "*20)
