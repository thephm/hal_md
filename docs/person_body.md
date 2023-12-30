# Person body

Here are some of the sections in the body of a person note:

- `# Person` should be replaced by the person's name e.g. `# SpongeBob SquarePants`
- `## Bio` is a brief description of the person
    - Usually from one of the numbered references and put [1], [2] etc. for the source of the info
- `## Quotes` is something they said
    - Usually from one of the numbered references and put [1], [2] etc. for the source of the info
- `## Life Events` are key moments in their life
    - format: `YYYY-MM-DD: <event>`
    - example: `2023-02-01: had a son, Thor 5lbs 2oz`
- `References` are hyperlinks to their profiles on social media sites, articles either mentioning them, about them, or by them
- `Products` is a numbered list of things this person worked on
    - Sometimes they are a backlink to a separate [Product](../templates/Product.md) Markdown file
    - Sometimes a hyperlink directly to an article they wrote or a Web page about the product
    - Sometimes just text
- `Positions` are a list of positions they've held
    - Could be work or volunteer
    - Format: <Title>, `[[Orgnanization]]`, `[[Place]], `YYYY` to `YYYY` or `#current`
    - Example: Fry Cook, [[Krusty Krab]], [[Bikini Bottom]], 1990 to 1993
    - Could append tags like `#quit`, `#fired`, `#promoted`, `#retired` 
- `People` are a list of people this person is connected to followed by a couple of words like "co-Founder" and [tags](tags.md) `#friend`
    - This is where the magic happens
    - They are typically wikilinks to other person files
    - Could be hyperlinks to a person on the Web if I haven't or don’t need to have them in my network
- `Interests` is a bulleted list of things they say they are interested in
    - may move this to a Front Matter field where it could be queried so I can ask questions like “Who are all the people I know that like embroidery?” (one of them!)
- `Communications` is for capturing any messages or emails with the person
    - Each sub-heading is the date in `### YYYY-MM-DD` format
    - For people with a lot of communications, keep separate files for each communication aka atomic notes and then embed them here
- `Notes` are just that, personal notes I take about the person

See [The Frontmatter](person_frontmatter.md) to learn about the structure of the top of the `person.md` template.