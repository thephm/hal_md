# Loads the interactions between people e.g. email, chat

import os
import sys
import datetime
import glob
import re

sys.path.insert(1, '../hal')
import interaction

sys.path.insert(1, './') 
import communication_file

NEW_LINE = "\n"

def get_interactions(slug, path, interactions):
    """
    Get the interaction file dates within a specific Person's folder.

    Parameters:
    slug (str): Person's slug e.g. 'spongebob
    path (str): Path to where the files are
    interactions (list): The collection of interactions

    Returns:
    str: The date of the most recent interaction
    """
    result = None
    markdown_file = communication_file.CommunicationFile()

    # match files starting with YYYY-MM-DD [12]
    pattern = r'^(\d{4}-\d{2}-\d{2})(?:\s-\s.*)?\.md$'

    # Get a list of file names matching the pattern
    files = [
        os.path.splitext(os.path.basename(file))[0]
        for file in glob.glob(os.path.join(path, '*'))
        if re.match(pattern, os.path.basename(file))
    ]
    if files:
        files.sort(reverse=True)

        for file in files:
            this_interaction = interaction.Interaction()
            this_interaction.slug = slug
            try:
                # extract the date portion using the regex
                match = re.match(pattern, file + ".md")
                if match:
                    date_part = match.group(1)  # extract the YYYY-MM-DD part
                    this_interaction.date = datetime.datetime.strptime(date_part, "%Y-%m-%d").date()

                    # store the filename in the Interaction object
                    this_interaction.filename = file + ".md"

                    # add the interaction to the list
                    interactions.append(this_interaction)

                # get the full pathname for the file
                full_path = os.path.join(path, file + ".md")
                markdown_file.path = full_path

                # read and parse the file's frontmatter
                markdown_file.frontmatter.read()

                # get the date from the frontmatter if it's a communication
                this_date = get_date(markdown_file)

                if this_date and (result is None or this_date > result):
                    result = this_date

            except Exception as e:
                print(f"Error processing file {file}: {e}")
                pass

        # Sort the interactions by reverse date
        interactions.sort(key=lambda x: x.date, reverse=True)

    return result

def get_date(file):
    """
    If the file is a communication e.g. the `tags` frontmatter field contains 
    "email", then return the frontmatter's `date` value. If not, return blank.
    
    Parameters:
    file (PersonFile): the file to get the date for.
    """

    date = ""

    for tag in file.frontmatter.tags:
        if tag in communication_file.Tags:
            the_date = file.frontmatter.get_date()
            break

    return the_date