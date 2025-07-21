# Class to create and modify a Markdown file's Frontmatter

# What's cool is it uses Pyhton's built in "setattr()" function to dynamically
# set the attributes of the object based on the set of "fields" that are
# configured by the user of this class. In this way, this class can be 
# inherited by other classes for specific Markdown files like "Person" or
# Organization.
#
# One default field "tags" is used for all instances of this class since it's
# an important field to determine the type of Object.
#
# Another special field is "slug" which is a unique label for an item of the 
# specific class. It's not defined in here but likely used in Classes that 
# inherit this one.

import yaml
import datetime

import md_person

FRONTMATTER_SEPARATOR = "---"

NEW_LINE = "\n"

TAG_NOTE = "note"
TAG_CHAT = "chat"
TAG_EMAIL = "email"
TAG_PHONE = "phone"
TAG_CALL = "call"
TAG_PERSON = "person"

FIELD_RAW = "raw"

# field in all Markdown files
FIELD_TAGS = "tags"

# fields in a communication Markdown files

FIELD_PEOPLE = "people"
FIELD_SERVICE = "service"
FIELD_TOPIC = "topic"
FIELD_DATE = "date"
FIELD_TIME = "time"

CommunicationFields = [FIELD_TAGS, FIELD_PEOPLE, FIELD_TOPIC, FIELD_DATE, FIELD_TIME, FIELD_SERVICE]

# keep a list of fields that are of type array
ArrayFields = [FIELD_TAGS]
    
class Frontmatter:
    def __init__(self, parent):
        self.parent = parent # file containing this frontmatter
        self.fields = []     # list of fields, dynamically set
        self.tags = []       # the tags for this file
        self.raw = ""        # the full text, all lines unparsed

    def __str__(self):
        output = ""
        for field in self.fields:
            value = getattr(self, field)
            if value:
                output += field + ": " + str(value) + NEW_LINE
        return output

    def get_date(self):
        return getattr(self, FIELD_DATE)
    
    def init_fields(self):
        """
        Initialize each field to [] if it's an array field or "" otherwise.
        """
        
        for field in self.fields:
            if field in ArrayFields:
                setattr(self, field, [])
            else:
                setattr(self, field, "")

    def check_fields(self, doc_fields):
        """
        See which fields are missing in the doc or extra, i.e. not a self.<field>
        """
        missing_fields = []
        extra_fields = []
        
        # Check for missing fields in self.fields
        for field_name in doc_fields:
            if not hasattr(self, field_name):
                missing_fields.append(field_name)
        
        # Check for extra fields in self.fields
        for field_name in self.fields:
            if field_name not in doc_fields:
                extra_fields.append(field_name)
        
        return missing_fields, extra_fields

    def get_field(self, doc, field, fields):
        """
        Read a specific field from the doc and return it's value.

        Parameters:
        doc (dict): The JSON text to be parsed
        field (str): The name of the field to obtain
        fields (list): Add the field to this collection

        Returns:
        str: The value of the field.
        """

        value = None

        try:
            if field in doc:
                if field == FIELD_DATE:
                    try:
                        value = datetime.datetime.strptime(str(doc[field]), '%Y-%m-%d').date()
                    except Exception as e:
                        pass
                
                elif field == FIELD_TIME:
                    value = doc[field]

                    # there are cases where the YAML parser sees the 
                    # frontmatter "time" value as an integer, e.g. 862
                    if isinstance(value, int):
                        # convert integer to hours and minutes
                        hours, minutes = divmod(value, 60)
                        # format the time as "HH:MM"
                        value = '{:02}:{:02}'.format(hours, minutes)
                else:
                    value = doc[field]

                setattr(self, field, value)
                fields.append(field)

        except Exception as e:
            print(e)
            pass

        return value

    def parse(self):
        """
        Parse the YAML frontmatter into fields.

        Returns:
        bool: True if valid YAML, False if not
        """
            
        result = False

        try:
            yamlData = yaml.safe_load_all(self.raw)
            for doc in yamlData:
                if isinstance(doc, dict):
                    for key in doc.keys():
                        if key not in self.fields:
                            self.fields.append(key)
                    for key, value in doc.items():
                        setattr(self, key, value)
                    result = True
        except Exception as e:
            print(e)

        return result
        
    def read(self):
        """
        Read the YAML frontmatter, parse it, and return True if it's valid.

        Parameters:
        None

        Returns:
        bool: True if valid YAML, False if not.

        Notes:
        If the file starts with "---" followed by one or more line(s), 
        followed by "---", the parse the YAML into the `frontmatter` fields.
        """

        result = False
        line = ""

        if not self.parent.file:
            self.parent.open('r')
        else:
            self.parent.file.seek(0)  # Reset pointer to start

        file = self.parent.file

        if file:
            try:
                # Skip leading blank lines
                while True:
                    firstLine = file.readline()
                    if not firstLine:
                        break  # EOF
                    firstLine = firstLine.strip()
                    if firstLine:  # Found a non-blank line
                        break

                if firstLine == FRONTMATTER_SEPARATOR:
                    self.raw += firstLine + NEW_LINE

                    # read lines until the second '---' is found or the end of the file is reached
                    for line in file:
                        line = line.strip()
                        self.raw += line + NEW_LINE
                        if line == FRONTMATTER_SEPARATOR:
                            result = True
                            break
            except Exception as e:
                print(e)

            if result:
                result = self.parse()

        return result
    
    def write(self):
        # if not already open, open the file in read-write mode
        if not self.parent.file:
            self.open('w+')

        file = self.parent.file
        file.write(self.get_yaml())
        
    def get_yaml(self): 
        result = FRONTMATTER_SEPARATOR + NEW_LINE

        for field in self.fields:
            value = getattr(self, field, None)
            # Only write if value is not None, not empty string, not empty list
            if value not in (None, "", []):
                result += f"{field}: {value}\n"

        result += FRONTMATTER_SEPARATOR + NEW_LINE
        return result