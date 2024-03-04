# Represents an interaction between two or more people e.g. email

import os
import sys
import datetime
import glob
import re

sys.path.insert(1, './') 
import communication_file

NEW_LINE = "\n"

# count the number of interactions
class InteractionsByMonth:
    def __init__(self):
        self.month = 0
        self.year = 0
        self.count = 0

class Interaction:
    def __init__(self):
        self.slug = 0
        self.date = None
        self.service = ""

    def __str__(self):
        output = self.slug + ": " + str(self.date)
        if self.service:
            output += " on " + self.service
        return output

class InteractionHistory:
    def __init__(self):
        self.slug = ""
        self.interactions = []
        self.date = None

    def __str__(self):
        output = ""
        for interaction in self.interactions:
            output += str(interaction) + NEW_LINE
        return output

# Get the most recent file date within a specific Person's folder
def getInteractions(slug, path, interactions):

    result = None
    markdownFile = communication_file.CommunicationFile()

    # the pattern for file names
    pattern = r'\d{4}-\d{2}-\d{2}\.md'

    # get a list of file names matching the pattern
    files = [os.path.splitext(os.path.basename(file))[0] for file in glob.glob(os.path.join(path, '*')) if re.match(pattern, os.path.basename(file))]
    if files:
        files.sort(reverse=True)

        for file in files:
            interaction = Interaction()
            interaction.slug = slug
            try: 
                interaction.date = datetime.datetime.strptime(file, "%Y-%m-%d").date()
                interactions.append(interaction)

                fullPath = os.path.join(path, file + ".md")
                
                markdownFile.path = fullPath

                # read and parse the frontmatter
                markdownFile.frontMatter.read()

                # get the date from the frontmatter if it's a communication
                thisDate = getDate(markdownFile)

                if thisDate and (result is None or thisDate > result):
                    result = thisDate

            except:
                pass

    return result

# -----------------------------------------------------------------------------
#
# If the file is a communication e.g. the `tags` frontmatter field contains 
# "email", then return the frontmatter's `date` value. If not, return blank.
#
# -----------------------------------------------------------------------------
def getDate(file):
    theDate = ""

    for tag in file.frontMatter.tags:
        if tag in communication_file.Tags:
            theDate = file.frontMatter.getDate()
            break

    return theDate