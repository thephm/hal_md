# Updates the "last_contact" frontmatter field based on atomic dated files.     

import os
from argparse import ArgumentParser

import sys
sys.path.insert(1, '../hal/')
import person

sys.path.insert(1, './') 
import md_person
import md_interactions

def get_arguments():
    """
    Parse the command line arguments.
    """

    parser = ArgumentParser()

    parser.add_argument("-f", "--folder", dest="folder", default=".",
                        help="The folder where each Person has a subfolder named with their slug")
    
    parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False,
                        help="Print extra info as the files processed")
    
    parser.add_argument("-t", "--template", dest="template", default=0,
                        help="Markdown template file")
    
    parser.add_argument("-x", "--max", type=int, dest="max", default=0,
                        help="Maximum number of people to process")
    
    args = parser.parse_args()

    return args

def update_last_contact(folder, the_interactions):
    """
    Given a set of interactions, update each Person's `last_contact` field
    
    Parameters:
    folder (str): Folder containing sub-folders for each person
    the_interactions (list): Collection of Interaction
    
    Returns:
    bool: True if success, False otherwise.

    Notes:
    #todo maybe use `Message` `from message_md` instead of `Interaction`

    As we go through the files, e.g. exclude "tags: note"
    """

    result = False
    the_date = ""

    # for each person find the most recent communication
    if the_interactions:

        # take the first (most recent) interaction
        most_recent_interaction = the_interactions[0]
        slug = most_recent_interaction.slug
        the_date = most_recent_interaction.date

        # update their profile
        if the_date:
            result = md_person.update_field(slug, folder, "last_contact", str(the_date))

    return result

def load_interactions(folder, the_interactions):
    """
    Given a folder name, load all of the interactions with that person and
    update the `last_contact` field with the date of the most recent interaction.
    
    Parameters:
    folder (str): Folder containing sub-folders for each person
    interactions (list): Collection of Interaction

    Returns:
    int: The number of interactions

    Notes:
    Populates `theInteractions` with all of the interactions e.g. chats
    that this person had and sorts them from most recent to oldest

    #todo maybe use `Message` `from message_md` instead of `Interaction`
    """

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
    print('The folder "' + args.folder + '" could not be found.')

elif folder:
    count = load_interactions(folder, the_interactions)

    print(str(count) + " people checked" + " "*20)
