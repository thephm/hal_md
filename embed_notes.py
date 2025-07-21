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
MD_EMBED = "!"
MD_SUFFIX = ".md"
EMBEDDED_WIKILINK = MD_EMBED + WIKILINK_OPEN

def get_arguments():
    """
    Parse the command line arguments.
    """
    parser = ArgumentParser()

    parser.add_argument("-f", "--folder", dest="folder", default=".",
                        help="The folder where each Person has a subfolder named with their slug")

    parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False,
                        help="Print extra info as the files processed")
    
    parser.add_argument("-x", "--max", type=int, dest="max", default=99999,
                        help="Maximum number of people to process")
    
    args = parser.parse_args()

    return args

def generate_markdown(slug, the_interactions):
    """
    Create a set of lines in Markdown with [[Wikilinks]] to each interaction.
    
    Parameters:
    slug (str): Person's slug e.g. 'spongebob'
    interactions (list): Collection of Interaction.

    Returns:
    str: Markdown text

    Notes:
    Generates a set of lines with embedded link to each communication file,
    separated by a blank line

    If there are two files `2023-02-01.md` and `2024-03-24.md`

    ```
    ![[spongebob/2023-02-01.md]]

    ![[spongebob/2024-03-24.md]]
    ```
    """
    markdown = ""

    # Sort the interactions chronologically from old to new
    sorted_interactions = sorted(the_interactions, key=lambda x: x.date)

    # Make a Wikilink to each interaction file so it can be embedded
    for interaction in sorted_interactions:
        markdown += EMBEDDED_WIKILINK
        markdown += slug + "/" + interaction.filename  # Use the filename from the Interaction object
        markdown += WIKILINK_CLOSE + NEW_LINE + NEW_LINE

    return markdown.strip()  # Remove trailing blank lines

def update_interactions(folder):
    """
    Given a folder name, load all of the interactions with that person based 
    on the existence of dated Markdown files for each date where an interaction 
    occured.

    Parameters:
    folder (str): Folder containing sub-folders for each person.

    Returns:
    int: The number of people processed.

    Notes:
    1. Go through each folder `folder-name` under `People`
    2. Find all files with names `YYYY-MM-DD`
    3. Create a list of them like this, ordered oldest to newest
    
    ```
    ![[spongebob/2017-08-13.md]]
    
    ![[spongebob/2022-12-06.md]]
    ```
   
    4. Open the corresponding person file where `slug` = `folder-name`
    5. Find the section `## Notes`
    6. After any bulleted list items (individual notes), replace what is 
        there with the new list of embedded files.
    """

    count = 0
    notes_section = md_person.SECTION_NOTES

    # get list of people `slug`s from the folder names
    slugs = md_person.get_slugs(folder)

    # for each person, find the most recent communication
    for slug in slugs:

        the_interactions = []
        top = ""

        # get all of the interactions with the person
        the_date = md_interactions.get_interactions(slug, os.path.join(folder, slug), the_interactions)
        
        if args.debug:
            print(slug + ": " + str(the_date))
    
        # generate the Notes section of the body
        interactions_markdown = generate_markdown(slug, the_interactions)
            
        # get the Person's profile 
        person_file = md_person.read_person_frontmatter(slug, folder)

        if person_file is not None:

            # get the part of the section before the embedded notes
            top = person_file.section_top(notes_section, EMBEDDED_WIKILINK)
            top = top.rstrip() # remove trailing whitespace [#21]

            # add the new content after the top, effectively replacing what's after top
            new_markdown = top + NEW_LINE + NEW_LINE + interactions_markdown
            
            # update what's in the Person's Notes section of their profile
            person_file.update_section(slug, notes_section, new_markdown)

            # write the file with the updated section
            result = person_file.save()

        count += 1
        
        # stop if we've reached the limit of the passed in `max` argument
        if args.max and count >= int(args.max): 
            return count

    return count

# main

args = get_arguments()
folder = args.folder
the_interactions = []

if folder and not os.path.exists(folder):
    print('The folder "' + folder + '" could not be found.')

elif folder:
    count = update_interactions(folder)
