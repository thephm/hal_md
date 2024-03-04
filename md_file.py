# Represents a Markdown file

import sys

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
        self.frontMatter = md_frontmatter.FrontMatter(self) # the frontmatter
        self.body = md_body.Body(self)  # the contents after the frontmatter

    def __str__(self):
        output = self.path + NEW_LINE
        output += str(self.frontMatter) + NEW_LINE
        output += str(self.body)
        return output
    
    def open(self, mode):
        self.file = open(self.path, mode)
    
    def save(self):
        # if not already open, open the file in read-write mode
        self.open('w+')
        self.frontMatter.write()
        self.body.write()
        self.file.close()
    