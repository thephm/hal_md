# Represents the body of a Markdown file

import sys
sys.path.insert(1, './') 

NEW_LINE = "\n"

# pairs in the section dictionary 
# e.g. {'heading': '## Bio', 'body': 'Born in 1964'}
SECTION_HEADING = 'heading'
SECTION_CONTENT = 'content'

SECTION_H1 = "# "
SECTION_H2 = "## "

class Body:

    def __init__(self, parent):
        self.parent = parent        # file containing this body
        self.section_headings = []  # possible headings e.g. `## Notes`
        self.sections = []          # each of the section's content
        self.raw = ""               # raw text from the file

    def __str__(self):
        output =  "sections: " + str(self.sections) + NEW_LINE
        output += "body: " + NEW_LINE + self.raw
        return output
    
    def read(self):

        if not self.parent.file:
            self.parent.open('r')

        # read the frontmatter, even if it was already read, so we know
        # that we're at the right spot in the file
        self.parent.frontmatter.read()

        # grab the handle to the file from the parent object
        file = self.parent.file

        # read the body of the file
        for line in file:
            self.raw += str(line)

        # parse the body by sections
        self.parse()

        return True
    
    # -------------------------------------------------------------------------
    #
    # Parse the body of a Markdown file into H1 and H2 sections.
    #
    # Notes:
    # 
    #   - Creates a collection of sections for the content of the Markdown file
    #   - Each section is like this:
    #
    #       {'heading': '# Spongebob Squarpants", 'contents': 'Ocean dweller'},
    #       {'heading': '## Bio", 'contents': 'Fictitious animated character'},
    #       {'heading': '## Life Events", 'contents': '- 2020:  Born'},
    #
    #   - Any content at the H3 or lower levels is kept in the `content` of the 
    #     H2 section that contains it.
    #
    # -------------------------------------------------------------------------
    def parse(self):

        self.sections = []  # Initialize sections list
    
        lines = self.raw.splitlines()  # Split the string into lines
        current_section = None

        for line in lines:
            # if this is a new section
            if line.startswith(SECTION_H1):
                if current_section is not None:
                    self.sections.append(current_section)
                # create a new section with level 1 heading
                current_section = {'heading': line, 'content': ''}
            elif line.startswith(SECTION_H2):
                if current_section is not None:
                    self.sections.append(current_section)
                # create a new section with level 2 heading
                current_section = {'heading': line, 'content': ''}
            elif current_section is not None:
                # add line to the content of the current section
                current_section['content'] += line + NEW_LINE

        # add the last section to the sections list
        if current_section is not None:
            self.sections.append(current_section)

    # -------------------------------------------------------------------------
    #
    # Writes the body of a Markdown file.
    #
    # Notes:
    #
    #   - Takes the parent file and writes each section heading and content
    # 
    # -------------------------------------------------------------------------
    def write(self):

        if not self.parent.file:
            self.parent.open('w+')

        # grab the handle to the file from the parent object
        file = self.parent.file

        file.write(NEW_LINE)
        for section in self.sections:
            file.write(section[SECTION_HEADING] + NEW_LINE)
            file.write(section[SECTION_CONTENT])

        return True  
    
    # get the content from a specific section of the file
    def get_content(self, section_heading):

        for section in self.sections:
            if section['heading'] == section_heading:
                return section['content']