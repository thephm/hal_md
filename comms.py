# Get the comms with a specific person   

import os
from argparse import ArgumentParser
import datetime

import sys
sys.path.insert(1, '../hal/')
import person
import identity

sys.path.insert(1, './') 
import md_lookup
import md_frontmatter
import md_body
import md_date
import md_interactions

sys.path.insert(1, './') 
import communication_file
import ansi_colors

import markdown
import html2text
import re

def remove_markdown(text):
    # convert Markdown to HTML
    html = markdown.markdown(text)
    
    # use html2text to strip HTML tags
    plain_text = html2text.html2text(html)

    # remove block quotes, including cases like "> >", ">>", or "> > >"
    plain_text = re.sub(r'(^|\n)\s*>+\s*', ' ', plain_text)  # Match one or more '>' with spaces

    # remove underscores used for italics (_italic_ or __bold__)
    plain_text = re.sub(r'(_{1,2})(.*?)\1', r'\2', plain_text)

    # replace custom image syntax like ![[filename|size]] with "(image)"
    plain_text = re.sub(r'!\[\[.*?\|?.*?\]\]', '(image)', plain_text)

    # replace video links like [[filename.mp4]] with "(video)"
    plain_text = re.sub(r'\[\[.*?\.mp4\]\]', '(video)', plain_text)

    # remove " at HH:MM" and replace with ":"
    plain_text = re.sub(r' at \d{1,2}:\d{2}', ':', plain_text)
    
    return plain_text

NEW_LINE = "\n"

# Parse the command line arguments
def get_arguments():

    parser = ArgumentParser()

    parser.add_argument("-f", "--folder", dest="folder", default=".",
                        help="The folder where each Person has a subfolder named with their slug")

    parser.add_argument("-s", "--slug", dest="slug", default=".",
                        help="The slug of the person e.g. 'sponge-bob'")

    parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False,
                        help="Print extra info as the files processed")
    
    parser.add_argument("-m", "--markdown", dest="markdown", action="store_true", default=False,
                        help="Display the Markdown instead of raw text")
    
    parser.add_argument("-t", "--time", dest="showtime", action="store_true", default=False,
                        help="Show the time e.g. SpongeBob at 23:31")
    
    parser.add_argument("-c", "--color", dest="color", action="store_true", default=False,
                        help="Use ANSI colors, otherwise just black/white text")
    
    parser.add_argument("-n", "--name", dest="name", default="",
                        help="The name of the person")
    
    parser.add_argument("-x", "--max", type=int, dest="max", default=3,
                        help="Maximum number of interactions to display")

    args = parser.parse_args()

    return args

# -----------------------------------------------------------------------------
#
# Given a folder name and a group of people (slugs), load recent interactions 
# with that person.
#
# Parameters:
# 
#   - folder - folder containing sub-folders for each person
#   - slug - person that is being looked up
#   - max - the maximum number of interactions to display
#   - color - True if we should include ANSI colors, False if not
#
# Returns:
#
#   - Nothing
#
# Notes:
# 
#   1. Find all files with names `YYYY-MM-DD` in the `folder`
#   2. Grab the body and collate the markdown
#
# -----------------------------------------------------------------------------
def get_interactions(folder, slug, max, color):

    count = 0
    the_markdown = ""

    the_interactions = []

    # get all of the interactions with the person
    the_date = md_interactions.get_interactions(slug, os.path.join(folder, slug), the_interactions)
    
    if args.debug:
        print(slug + ": " + str(the_date))

    for interaction in the_interactions:
        the_date = interaction.date
        the_file = communication_file.CommunicationFile()
        the_file.path = os.path.join(folder, slug + "/" + str(the_date) + ".md")
        the_file.open('r')

        if the_file is not None:

            the_file.frontmatter.read()

            file_date = getattr(the_file.frontmatter, md_frontmatter.date)
            the_service = getattr(the_file.frontmatter, md_frontmatter.service)
            if color:
                the_markdown += ansi_colors.BG_BLUE
            the_markdown += str(file_date)
            if color: 
                the_markdown += ansi_colors.RESET
            the_markdown += " via " + str(the_service) + NEW_LINE + NEW_LINE
            the_file.body.read()
            the_markdown += str(the_file.body.raw)
        
            count += 1
            if count >= max: 
                break

    return the_markdown

# main

args = get_arguments()
folder = args.folder

if folder and not os.path.exists(folder):
    print('The folder "' + folder + '" could not be found.')

elif folder:
    the_markdown = get_interactions(folder, args.slug, args.max, args.color)
    if not args.markdown: 
        the_markdown = remove_markdown(the_markdown)
    
    print(the_markdown)
