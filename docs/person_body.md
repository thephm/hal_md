# Person body

Here are some of the sections in the body of a person note:

- `# Person` is their full name e.g. `# SpongeBob SquarePants`
- `## Bio` is a brief description of the person
    - Usually from one of the numbered references and put `[1]`, `[2]` etc. for the source of the info
- `## Quotes` is something they said
    - Usually from one of the numbered references and put `[1]`, `[2]` etc. for the source of the info
- `## Life Events` are key moments in the person's life
    - Format: `YYYY-MM-DD: <event>`
    - Example: `2023-02-01: had a son, Thor 5lbs 2oz`
- `References` are hyperlinks to more information on the Web
    - Examples: profiles on social media sites, articles mentioning them, about them, or by them
- `Products` is a bulleted list of things this person worked on
    - Sometimes they are a backlink to a separate [Product](../templates/Product.md) Markdown file
    - Sometimes a hyperlink directly to an article they wrote or a Web page about the product
    - Sometimes just text
- `Positions` is a bulleted list of positions they've held
    - Could be work or volunteer
    - Format: `<Title>, [[Orgnanization]], [[Place]], YYYY to YYYY` or `#current` and `#tag1 #tag2`
    - Example: `Fry Cook, [[Krusty Krab]], [[Bikini Bottom]], 1990 to 1993 #quit`
    - Could append tags like `#quit`, `#fired`, `#promoted`, `#retired` 
- `People` are a list of `[[First Name Last Name]]` wikilinks to people this person is connected to
    - This is where the magic happens!
    - They are typically wikilinks to other person files
    - Append a few words like "- co-Founder" and [tags](tags.md) like `#friend`
    - Example: `[[Patrick]] #friend #very-strong`
    - Could be hyperlinks to a person on the Web don’t need to have them in your network
- `Interests` is a bulleted list of things they are interested in
    - may move this to a Front Matter field where it could be queried so you can ask questions like “Who are all the people I know that like embroidery?” (one of them!)
- `Communications` is for capturing any messages or emails with the person
    - Each sub-heading is the date in `### YYYY-MM-DD` format
    - For people with a lot of communications, keep separate files for each communication aka atomic notes and then embed them here
- `Notes` are just that, personal notes about the person

See [The Frontmatter](person_frontmatter.md) to learn about the structure of the top of the `person.md` template.
