# Represents a Markdown file

import sys
import os

sys.path.insert(1, './') 
import md_frontmatter
import md_body

NEW_LINE = "\n"

TAG_NOTE = "note"

# field in all Markdown files
FIELD_TAGS = "tags"

Tags=[TAG_NOTE]

class File:
    def __init__(self):
        self.path = ""   # path to the file
        self.file = None # file handle
        self.frontmatter = md_frontmatter.Frontmatter(self) # the frontmatter
        self.body = md_body.Body(self)  # the contents after the frontmatter

    def __str__(self):
        output = self.path + NEW_LINE
        output += str(self.frontmatter) + NEW_LINE
        output += str(self.body)
        return output
    
    def open(self, mode):
        self.file = open(self.path, mode)
    
    def save(self):
        # open the file in read-write mode
        self.open('w+')
        self.frontmatter.write()
        self.body.write()
        self.file.close()
    
def get_prefix(path):
    fileName = os.path.basename(path)  # get the base name of the file
    filePrefix = os.path.splitext(fileName)[0]  # remove the extension
    return filePrefix