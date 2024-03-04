# The Person's body

Here are some of the sections in the body of a person note:

Section | Description | Example
--|---|---
`# Person` | Their full name | `# SpongeBob SquarePants`
`## Bio` | A brief description of the person. Usually from one of the numbered references and put `[1]`, `[2]` etc. for the source of the info | `> an American animated television series created by marine science educator and animator Stephen Hillenburg - [1]`
`## Quotes` | Something they said. Usually from one of the numbered references and put `[1]`, `[2]` etc. for the source of the info | `> Aye-aye, captain!`
`## Life Events` | Key moments in the person's life. Format: `YYYY-MM-DD: <event>` | `2023-02-01: had a son, Thor 5lbs 2oz`
`References` | Hyperlinks to more information on the Web such as profiles on social media sites, articles mentioning them, about them, or by them | `1. [Wikipedia](https://en.wikipedia.org/wiki/SpongeBob_SquarePants)`
`## Products` | A bulleted list of things this person worked on.\nSometimes they are a backlink to a separate [Product](../templates/Product.md) Markdown file\nSometimes a hyperlink directly to an article they wrote or a Web page about the product.\nSometimes just text | `- [[Dynalist]]`
`## Positions`| A bulleted list of positions they've held. Could be work or volunteer.\nFormat: `<Title>, [[Orgnanization]], [[Place]], YYYY to YYYY` or `#current` and `#tag1 #tag2`\n Could append tags like `#quit`, `#fired`, `#promoted`, `#retired`. | `- Fry Cook, [[Krusty Krab]], [[Bikini Bottom]], 1990 to 1993 #quit`
`## People` | A list of `[[First Name Last Name]]` wikilinks to people this person is connected to. This is where the magic happens! They are typically wikilinks to other person files. Append a few words like "- co-Founder" and [tags](tags.md) like `#friend`. Could be hyperlinks to a person on the Web don’t need to have them in your network | `[[Patrick]] - met at work #friend #very-strong`
`## Interests` | A bulleted list of things they are interested in. May move this to a Front Matter field where it could be queried so you can ask questions like “Who are all the people I know that like embroidery?” (one of them!) | `- Jellyfishing`
`## Notes` | Just that, personal notes about the person | `- Our son used to love this cartoon`
`## Communications` | For capturing any messages or emails with the person. Each sub-heading is the date in `### YYYY-MM-DD` format. For people with a lot of communications, keep separate files for each communication aka atomic notes and then embed them here | `![[spongebob/2023-12-30.md]]`

See [The Frontmatter](person_frontmatter.md) to learn about the structure of the top of the `person.md` template.
