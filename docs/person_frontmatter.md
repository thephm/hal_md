# The Person's head

At the top of each [person.md](../templates/Person.md) is what's called the the frontmatter. If you're not technical, don't let it scare you. It's just a bunch of fields like in a form. In this case, it's the information about the person.

### Why

Having some structured metadata (data about the data, in this case data about the person) is helpful to be able to query across all of your notes and to be able to answer questions like "Who in my network knows Java?"

### What

Frontmatter is a collection of fields at the top of a note delineated by three dashes --- before and after the fields.

### Fields

Here are some of the fields in the top my person files:

- `tags` are individual labels
    - Always has `person` preferably the first one but not mandatory
    - Example: `software-developer`, `friend`, `ex-colleague`
- `subject-id` is the unique ID for this person (optional)
- `aliases` are for a nickname or preferred name
    - If this is someone close to you, just put their first name or nickname
    - So can link to them with `[[FirstName LastName|FirstName]]` e.g. `[[SpongBob SquarePants|SpongeBob]]`
- `slug` is a one-word or hyphenated label **unique** to that person
    - Must be unique
    - Used for their folder name under `People` folder
    - Used in `people:` fields in other files like [Chat.md](../templates/Chat.md) or `from:` or `to:` in [Email.md](../templates/Email.md)
    - Helpful for queries
- `birthday` is one of the most important fields!
    - `YYYY-MM-DD` 
    - `"MM-DD"` if you don't know the year
        - you may need to switch to source mode in Obsidian otherwise the date-picker expects a fully qualified date
- `title` is their current job title
    - thinking to remove this since already under `## Positions` with label `#current`
- `skills` are a comma-separated list of one-word or hyphenated words skills the person has 
    - Example: `[java, spring-boot, css]`
- `organizations` is a collection of organizations
    - The current organization(s) they are at
    - Matches `slug` in the corresponding [Organization.md](../templates/Organization.md)` note file on the company the person is affiliated with
- `url` is the primary Web site to visit for this person if they have one
- `products` is a comma-separated list of product slugs that the person worked
    - Example: `[obsidian, dynalist]`
    - Could be redundant if also in `## Products` so may be removed
- `hometown` is where they are originally from
- `city` and `state` are where they live
- `x-id` and `linkedin-id` are the last portion of their X (Twitter) or LinkedIn URL
    - Could be redundant if also in `## References` so may be removed

For some people I add fields:

- `anniversary` for their wedding anniversary
- `address` for their street address
- `zip` for the postal/ZIP code
- `github-id`, `threads-id`, `reddit-id` etc. 

See [The Body](person_body.md) to learn about the structure of the rest of the `person.md` template.
