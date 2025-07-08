# Gets a list of birthdays by month     

import os
from argparse import ArgumentParser
import datetime
import calendar

import sys
sys.path.insert(1, '../hal/')
import person
import identity
import life_events

sys.path.insert(1, './') 
import md_lookup
import md_date

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

# Parse the command line arguments
def get_arguments():

    parser = ArgumentParser()

    parser.add_argument("-f", "--folder", dest="folder", default=".",
                        help="The folder where each Person has a subfolder named with their slug")
    
    parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False,
                        help="Print extra info as the files processed")
    
    parser.add_argument("-u", "--upcoming", type=int, dest="upcoming", default=None,
                        help="Show the birthdays upcoming in the next number of days")
    
    parser.add_argument("-x", "--max", type=int, dest="max", default=99999,
                        help="Maximum number of people to process")
    
    args = parser.parse_args()

    return args

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
        slug = birthday[person.slug]
        name = birthday[identity.name]
        date = birthday[life_events.birthday]
        deathday = birthday[life_events.deathday]
        if date and md_date.extract_month(date) and md_date.extract_day(date):
            valid_birthdays.append((name, slug, date, deathday))
        elif date and date != None and date != "None":
           print("Invalid birthday: '" + str(birthday) + "'")

    # sort valid birthdays by birthday
    sorted_birthdays = sorted(valid_birthdays, key=lambda x: (int(md_date.extract_month(x[PAIR_BIRTHDAY]) or 0), int(md_date.extract_day(x[PAIR_BIRTHDAY]) or 0)))

    return sorted_birthdays

def calculate_age(birthday, deathday):

    # parse the birthday and deathday strings into datetime objects
    birth_date = md_date.get_date(birthday)
    death_date = md_date.get_date(deathday)

    if death_date:
        age = death_date.year - birth_date.year - ((death_date.month, death_date.day) < (birth_date.month, birth_date.day))
    elif deathday:
           print("Invalid deathday: '" + str(deathday) + "'")
    else:
        try:
            # calculate the current age
            current_date = datetime.datetime.now()
            age = current_date.year - birth_date.year - ((current_date.month, current_date.day) < (birth_date.month, birth_date.day))
        except:
           print("Invalid birthday: '" + str(birthday) + "'")

    return age

# -----------------------------------------------------------------------------
#
# Display the birthdays coming up in the next `num_days` days
#
# Parameters:
#
#   birthdays - collection of {slug, name, birthday, deathday}
#   num_days - the number of days (including today) forward to look
#
# -----------------------------------------------------------------------------
def upcoming(birthdays, num_days):

    output = ""

    # calculate the current age
    current_date = datetime.datetime.now()
    current_month = current_date.month
    current_day = current_date.day

    # calculate the date `num_days` from now
    end_date = datetime.datetime.now() + datetime.timedelta(days=num_days)

    for birthday in birthdays:

        # parse the birthday string
        the_month = int(md_date.extract_month(birthday[PAIR_BIRTHDAY]))
        the_day = int(md_date.extract_day(birthday[PAIR_BIRTHDAY]))
    
        if 1 <= the_month <= 12 and 1 <= the_day <= 31:
            # calculate the birthday's date for the current year
            birthday_date = datetime.datetime(datetime.datetime.now().year, the_month, the_day)

            # if the birthday falls within the next num_days, include it
            if datetime.datetime.now() <= birthday_date <= end_date:
                output += birthday[PAIR_NAME] + " on " + calendar.month_abbr[the_month] + " " + str(the_day) + NEW_LINE

        else:
            print("Invalid birthday: " + str(birthday))

    return output

# -----------------------------------------------------------------------------
#
# Generate a calendar of birthdays in Markdown 
#
# Parameters:
#
#   birthdays - collection of {slug, name, birthday, deathday}
#
# -----------------------------------------------------------------------------
def make_calendar(birthdays):

    output = ""

    # group birthdays by month
    grouped_birthdays = {}
    for birthday in birthdays:
        month = md_date.extract_month(birthday[PAIR_BIRTHDAY])
        if month in grouped_birthdays:
            grouped_birthdays[month].append(birthday)
        else:
            grouped_birthdays[month] = [birthday]

    # print birthdays by month
    for month_num in range(1, 13):
        output += HEADING_2 + " " + calendar.month_name[month_num] + NEW_LINE + NEW_LINE

        month_num_str = str(month_num).zfill(2)

        if month_num_str in grouped_birthdays:

            output+= BIRTHDAY_TABLE_HEADING

            # sort birthdays within the month
            sorted_birthdays = sorted(grouped_birthdays[month_num_str], key=lambda x: md_date.extract_day(x[PAIR_BIRTHDAY]))
            
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
                    year = birthdayStr[:4]
                    age = str(calculate_age(birthdayStr, deathdayStr))

                output += day + TABLE_SEPARATOR + name + TABLE_SEPARATOR + year + TABLE_SEPARATOR + age + NEW_LINE

        if month_num != 12:
            output += NEW_LINE + NEW_LINE

    return output

# main

args = get_arguments()
folder = args.folder

the_calendar = ""

if folder and not os.path.exists(folder):
    print('The folder "' + folder + '" could not be found.')

elif folder:
    birthdays = md_lookup.get_values(folder, [life_events.birthday, life_events.deathday], args)
    sorted_birthdays = sort_birthdays(birthdays)

    if args.upcoming:
        print(upcoming(sorted_birthdays, args.upcoming))
    else:
        the_calendar = make_calendar(sorted_birthdays)
        print(the_calendar)
