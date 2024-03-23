# Include the individual, dated Markdown note files into the Person's profile
# under `## Notes` so you can see the entire communication history with them.   

import os
from argparse import ArgumentParser
import datetime

import sys
sys.path.insert(1, '../hal/')
import person
import identity

sys.path.insert(1, './') 
import md_lookup
import md_person
import md_frontmatter
import md_body
import md_date
import md_interactions

NEW_LINE = "\n"
HEADING_2 = "##"
HEADING_NOTES = HEADING_2 + " Notes"
WIKILINK_OPEN = "[["
WIKILINK_CLOSE = "]]"

# Parse the command line arguments
def get_arguments():

    parser = ArgumentParser()

    parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False,
                        help="Print extra info as the files processed")
    
    parser.add_argument("-x", "--max", type=int, dest="max", default=99999,
                        help="Maximum number of people to process")
    
    args = parser.parse_args()

    return args

# -----------------------------------------------------------------------------
#
# Given a folder name, load all of the interactions with that person based on
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
#   - 
#
# Notes:
# 
#   1. Go through each folder `folder-name` under `People`
#   2. Find all files with names `YYYY-MM-DD`
#   3. Create a list of them like this, ordered oldest to newest
#
#   ```
#   ![[spongebob/2017-08-13]]
#
#   ![[spongebob/2022-12-06]]
#   ```
#
#   4. Open the corresponding person file where `slug` = `folder-name`
#   5. Find the section `## Notes`
#   6. After any bulleted list items (individual notes), replace what is there
#      with the new list of embedded files.
#
# -----------------------------------------------------------------------------
def load_interactions(folder, the_interactions):

    count = 0

    # get list of people `slug`s from the folder names
    slugs = md_person.get_slugs(folder)

    # for each person find the most recent communication
    for slug in slugs:
        the_interactions = []

        # get all of the interactions with the person
        the_date = md_interactions.get_interactions(slug, os.path.join(folder, slug), the_interactions)

        # update the `last_contact` field for the person
        update_last_contact(folder, the_interactions)

        # stop if we've reached the limit of the passed in `max` argument
        if args.max and count >= int(args.max): 
            return count
        
        if args.debug:
            print(slug + ": " + str(the_date))

        count += 1
    
    return count

# main

args = get_arguments()
folder = args.folder
the_interactions = []

if folder and not os.path.exists(folder):
    print('The folder "' + folder + '" could not be found.')

elif folder:
    count = load_interactions(folder, the_interactions)
