# Gets a list of birthdays by month     

import os
from argparse import ArgumentParser
import datetime

import sys
sys.path.insert(1, '../hal/')
import person
import identity
import life_events

sys.path.insert(1, './') 
import md_lookup

NEW_LINE = "\n"
HEADING_2 = "##"
BIRTHDAY_TABLE_HEADING = "Day | Person | Year | Age\n:-:|---|:-:|:-:\n"
TABLE_SEPARATOR = " | "
WIKILINK_OPEN = "[["
WIKILINK_CLOSE = "]]"

# A birthday contains {name, slug, birthday}
PAIR_NAME = 0
PAIR_SLUG = 1
PAIR_BIRTHDAY = 2
PAIR_DEATHDAY = 3
MONTH_NUMBER_DEC = "12"
MONTH_DECEMBER = "December"

# Parse the command line arguments
def get_arguments():

    parser = ArgumentParser()

    parser.add_argument("-f", "--folder", dest="folder", default=".",
                        help="The folder where each Person has a subfolder named with their slug")
    
    parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False,
                        help="Print extra info as the files processed")
    
    parser.add_argument("-x", "--max", type=int, dest="max", default=99999,
                        help="Maximum number of people to process")
    
    args = parser.parse_args()

    return args

def extract_year(dateString):
    if "-" in dateString:
        if len(dateString) == 10:  # YYYY-MM-DD format
            return dateString[0:4]
        elif len(dateString) == 5: # MM-DD format
            return ""
        else:
            print("Invalid date: '" + dateString + "'")

def extract_month(dateString):
    if "-" in dateString:
        if len(dateString) == 10:  # YYYY-MM-DD format
            return dateString[5:7]
        elif len(dateString) == 5:  # MM-DD format
            return dateString[0:2]
        else:
            print("Invalid date: '" + dateString + "'")
        
def extract_day(dateString):
    if "-" in dateString:
        if len(dateString) == 10:  # YYYY-MM-DD format
            return dateString[8:10]
        elif len(dateString) == 5:  # MM-DD format
            return dateString[3:5]
        else:
            print("Invalid date: '" + dateString + "'")

# -----------------------------------------------------------------------------
#
# Sort a collection of birthdays in chronological order from Jan to Dec 
#
# Parameters:
#
#   birthdays - collection of {slug, birthday}
#
# Notes:
# 
#   - Some birthdays in form `YYYY-MM-DD` and some `MM-DD`
#
# -----------------------------------------------------------------------------
def sort_birthdays(birthdays):

    valid_birthdays = []

    # filter out birthdays with missing or invalid dates
    for birthday in birthdays:
        slug = birthday[person.FIELD_SLUG]
        name = birthday[identity.FIELD_NAME]
        date = birthday[life_events.FIELD_BIRTHDAY]
        deathday = birthday[life_events.FIELD_DEATHDAY]
        if date and extract_month(date) and extract_day(date):
            valid_birthdays.append((name, slug, date, deathday))
        else:
            print("Invalid birthday:", name, slug, date, deathday)

    # sort valid birthdays by birthday
    sorted_birthdays = sorted(valid_birthdays, key=lambda x: (int(extract_month(x[PAIR_BIRTHDAY]) or 0), int(extract_day(x[PAIR_BIRTHDAY]) or 0)))

    return sorted_birthdays

def calculate_age(birthday, deathday):

    result = {}  # Create an empty dictionary to store the result

    # parse the birthday string into a datetime object
    if "-" in birthday:
        if len(birthday) == 10:  # YYYY-MM-DD format
            birth_date = datetime.datetime.strptime(birthday, "%Y-%m-%d")
        elif len(birthday) == 5:  # MM-DD format
            birth_date = datetime.datetime.strptime(birthday, "%m-%d")

    if "-" in deathday:
        # calculate the age at death
        if len(deathday) == 10:  # YYYY-MM-DD format
            death_date = datetime.datetime.strptime(deathday, "%Y-%m-%d")
        elif len(deathday) == 5:  # MM-DD format
            death_date = datetime.datetime.strptime(deathday, "%m-%d")
        age = death_date.year - birth_date.year - ((death_date.month, death_date.day) < (birth_date.month, birth_date.day))
    else:
        # calculate the current age
        current_date = datetime.datetime.now()
        age = current_date.year - birth_date.year - ((current_date.month, current_date.day) < (birth_date.month, birth_date.day))
    
    return age

# -----------------------------------------------------------------------------
#
# Generate a calendar of birthdays in Markdown 
#
# Parameters:
#
#   birthdays - collection of {slug, birthday}
#
# -----------------------------------------------------------------------------
def make_calendar(birthdays):

    output = ""

    # dictionary mapping numeric month values to full month names
    month_names = {
        "01": "January", "02": "February", "03": "March", "04": "April", "05": "May", "06": "June",
        "07": "July", "08": "August", "09": "September", "10": "October", "11": "November", 
        MONTH_NUMBER_DEC: MONTH_DECEMBER
    }

    # group birthdays by month
    grouped_birthdays = {}
    for birthday in birthdays:
        month = extract_month(birthday[PAIR_BIRTHDAY])
        if month in grouped_birthdays:
            grouped_birthdays[month].append(birthday)
        else:
            grouped_birthdays[month] = [birthday]

    # print birthdays by month
    for month_num, month_name in month_names.items():
        output += HEADING_2 + " " + month_name + NEW_LINE + NEW_LINE
        if month_num in grouped_birthdays:

            output+= BIRTHDAY_TABLE_HEADING

            # sort birthdays within the month
            sorted_birthdays = sorted(grouped_birthdays[month_num], key=lambda x: extract_day(x[PAIR_BIRTHDAY]))
            for birthday in sorted_birthdays:
                name = WIKILINK_OPEN + birthday[PAIR_NAME] + WIKILINK_CLOSE
                birthdayStr = birthday[PAIR_BIRTHDAY]
                try:
                    deathdayStr = birthday[PAIR_DEATHDAY]
                except:
                    deathdayStr = ""

                year=""
                age=""
                day = birthdayStr[-2:]
                
                if len(birthdayStr) == 10:  # YYYY-MM-DD format
                    age = str(calculate_age(birthdayStr, deathdayStr))
                    year = birthdayStr[:4]

                output += day + TABLE_SEPARATOR + name + TABLE_SEPARATOR + year + TABLE_SEPARATOR + age + NEW_LINE

        if month_num != MONTH_NUMBER_DEC:
            output += NEW_LINE + NEW_LINE

    return output

# main

args = get_arguments()
folder = args.folder

interactions = []

if folder and not os.path.exists(folder):
    print('The folder "' + folder + '" could not be found.')

elif folder:
    birthdays = md_lookup.get_values(folder, [life_events.FIELD_BIRTHDAY, life_events.FIELD_DEATHDAY], args.max)
    sorted_birthdays = sort_birthdays(birthdays)
    calendar = make_calendar(sorted_birthdays)
    print(calendar)
