# The Person's head

At the top of the [Person.md](../templates/Person.md) is what's called the the frontmatter. If you're not technical, don't let it scare you. It's just a bunch of fields like in a form. In this case, it's the information about the person.

### Why

Having structured metadata -- data about the data which, in this case, is data about the person -- is helpful to be able to query across all of your notes and to be able to answer questions like "Who in my network knows Java?"

### What

Frontmatter is a collection of fields at the top of a note delineated by three dashes `---` before and after the fields like this:

```
---
tags: [person, friend, ex-colleague, blist]
first-name: SpongeBob
last-name: SquarePants
---
```

### Fields

Here are the fields in the top of the [Person.md](../templates/Person.md) template:

Field | Description | Example
--|---|---
`tags` | Individual labels. Always include `person` preferably the first one but doesn't have to be | `software-developer`, `friend`, `ex-colleague`
`subject-id` | Don't use this as it will be removed as it was for me to reference my HAL system, you don't need it
`aliases` | Nickname or preferred name. Can then link to the person with this alias. See the Obsidian [Aliases](https://help.obsidian.md/Linking+notes+and+files/Aliases) Help page | `[SpongeBob, Bob]`
`slug` | A one-word or hyphenated label **unique** to that person. Must be unique. Used for their folder name under `People` folder. Used in `people:` fields in other files like [Chat.md](../templates/Chat.md) or `from:` or `to:` in [Email.md](../templates/Email.md). Helpful for queries. | `spongebob`
`birthday` | One of the most important fields!\nFormat: `YYYY-MM-DD` or `"MM-DD"` if you don't know the year.\nTo use the month and day only, you may need to switch to source mode in Obsidian otherwise the date-picker expects a fully qualified date | `1965-09-29` or `09-29`
`title` | Their current job title. Thinking to remove this since already under `## Positions` with label `#current` | `Fry Cook`
`skills` | A comma-separated list of one-word or hyphenated words skills the person has. | `[java, spring-boot, css]`
`organizations` | A collection of organizations. The current organization(s) they are at. Matches `slug` in the corresponding [Organization.md](../templates/Organization.md)` note file on the company the person is affiliated with | `[krusty-krab, mcdondalds]`
`url` | The primary Web site to visit for this person if they have one | `https://www.spongebob.com`
`products` | A comma-separated list of product slugs that the person worked on. Could be redundant if also in `## Products` so may be removed | `[obsidian, dynalist]`
`hometown` | Where they are originally from | `Bikini Bottom, Marshall Islands`
`city` | City where they live | `Bikini Bottom`
`state` | Province or State where they live | `Marshall Islands`
`x-id` | The last portion of their X (Twitter) social network URL. Could be redundant if also in `## References` so may be removed | `spongebob`
`linkedin-id` | The last portion of their LinkedIn social network URL. Could be redundant if also in `## References` so may be removed | `spongebobrocks`

For some people I add fields:

- `anniversary` for their wedding anniversary. See `birthday` for the format
- `address` for their street address
- `zip` for the postal/ZIP code
- `github-id`, `threads-id`, `reddit-id` etc. 

See [The Body](person_body.md) to learn about the structure of the rest of the `person.md` template.
