import datetime

def extract_year(dateString):
    if "-" in dateString:
        if len(dateString) == 10:  # YYYY-MM-DD format
            return dateString[0:4]
        elif len(dateString) == 5: # MM-DD format
            return ""

def extract_month(dateString):
    if "-" in dateString:
        if len(dateString) == 10:  # YYYY-MM-DD format
            return dateString[5:7]
        elif len(dateString) == 5:  # MM-DD format
            return dateString[0:2]
        
def extract_day(dateString):
    if "-" in dateString:
        if len(dateString) == 10:  # YYYY-MM-DD format
            return dateString[8:10]
        elif len(dateString) == 5:  # MM-DD format
            return dateString[3:5]

def get_date(dateStr):
    """
    Parse a date string of format `YYYY-MM-DD` or `MM-DD` into datetime object
    """

    the_date = None
    
    if "-" in dateStr:
        if len(dateStr) == 10:  # YYYY-MM-DD format
            try:
                the_date = datetime.datetime.strptime(dateStr, "%Y-%m-%d")
            except:
                print("invalid date: '" + str(dateStr) + "'")
        elif len(dateStr) == 5:  # MM-DD format
            try:
                the_date = datetime.datetime.strptime(dateStr, "%m-%d")
            except:
                print("invalid date: '" + str(dateStr) + "'")

    return the_date