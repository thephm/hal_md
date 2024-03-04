# Represents the body of a Markdown file

import sys
sys.path.insert(1, './') 

NEW_LINE = "\n"

class Body:
    def __init__(self, parent):
        self.parent = parent # file containing this body
        self.raw = ""  # raw text from the file
        self.sections = [] # each of the sections

    def __str__(self):
        output =  "sections: " + str(self.sections) + NEW_LINE
        output += "body: " + NEW_LINE + self.raw
        return output
    
    def read(self):

        if not self.parent.file:
            self.parent.open('r')

        # read the frontmatter, even if it was already read, so that we know 
        # we're at the right spot in the file
        self.parent.frontMatter.read()

        # grab the handle to the file from the parent object
        file = self.parent.file

        for line in file:
            self.raw += str(line)

        # @todo: parse the body by sections

        return True
    
    def write(self):

        if not self.parent.file:
            self.parent.open('w+')

        # grab the handle to the file from the parent object
        file = self.parent.file
        file.write(self.raw)

        return True  
