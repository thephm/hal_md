# Loads the interactions between people e.g. email, chat

import os
import sys
import datetime
import glob
import re

sys.path.insert(1, './hal') 
import interaction

sys.path.insert(1, './') 
import communication_file

NEW_LINE = "\n"

# Get the most recent interaction file date within a specific Person's folder
def get_interactions(slug, path, this_interactions):

    result = None
    markdown_file = communication_file.CommunicationFile()

    # the pattern for file names
    pattern = r'\d{4}-\d{2}-\d{2}\.md'

    # get a list of file names matching the pattern
    files = [os.path.splitext(os.path.basename(file))[0] for file in glob.glob(os.path.join(path, '*')) if re.match(pattern, os.path.basename(file))]
    if files:
        files.sort(reverse=True)

        for file in files:
            this_interaction = interaction.Interaction()
            this_interaction.slug = slug
            try: 
                this_interaction.date = datetime.datetime.strptime(file, "%Y-%m-%d").date()
                this_interactions.append(this_interaction)

                # get the full pathname for the file
                full_path = os.path.join(path, file + ".md")
                markdown_file.path = full_path
                
                # read and parse the file's frontmatter
                markdown_file.frontmatter.read()

                # get the date from the frontmatter if it's a communication
                thisDate = get_date(markdown_file)

                if thisDate and (result is None or thisDate > result):
                    result = thisDate

            except:
                pass

        # sort the interactions by reverse date
        this_interactions.sort(key=lambda x: x.date, reverse=True)

    return result

# -----------------------------------------------------------------------------
#
# If the file is a communication e.g. the `tags` frontmatter field contains 
# "email", then return the frontmatter's `date` value. If not, return blank.
#
# -----------------------------------------------------------------------------
def get_date(file):
    theDate = ""

    for tag in file.frontmatter.tags:
        if tag in communication_file.Tags:
            the_date = file.frontmatter.get_date()
            break

    return the_date