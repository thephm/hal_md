# The Person's Head

At the top of each [person.md](../templates/Person.md) is what's called the the frontmatter. If you're not technical, don't let it scare you. It's just a bunch of fields like in a form. In this case, it's the information about the person.

Why? Having some structured metadata (data about the data, in this case data about the person) is helpful to be able to query across. Be able to answer questions like "Who in my network knows Java?"

Frontmatter is a collection of fields at the top of a note delineated by three dashes --- before and after the fields.

Here are some of the fields in the top my person files:

- `tags` are individual labels such as note-app if this is a person who works on or talks about a note-taking app
- `subject-id` is the unique ID in my HAL system for this person
- `aliases` are for a nickname or preferred name
    - Often put their first name so in notes can use `[[FirstName LastName|FirstName]]` e.g. `[[SpongBob SquarePants|SpongeBob]]`
    - If this is someone close, just put their first name. 
- `slug` is a one-word or hyphenated label that’s unique for that person
    - used for their folder name under `People` folder
    - used in `people:` fields in other files like [Chat.md](../templates/Chat.md) or `from:` or `to:` in [Email.md](../templates/Email.md)
    - helpful for queries
- `birthday` is one of the most important ones
    - `YYYY-MM-DD` 
    - `"MM-DD"` if you don't know the year (may need to switch to source mode in Obsidian otherwise the date-picker expects a fully qualified date)
- `title` - current job title
    - thinking to remove this since already under positions
- `skills` are a comma-separated list of one-word or hyphenated words skills the person has 
    - example `[java, spring-boot, css]`
- `organizations` is a collection of organizations
    - I put here the current organization but you could put slugs of all the organizations
    - matches `slug` in the corresponding [Organization.md](../templates/Organization.md)` note file on the company the person is affiliated with
- `url` is the primary Web site to visit for this person if they have one
- `products` is a comma-separated list of product slugs that the person worked on e.g. `[obsidian, dynalist]`
- `hometown` is where they are originally from
- `city`, `stte`
- `x-id`, `linkedin-id`, ``

For some people I add fields:

- `anniversary` - for their wedding anniversary
- `address` - for their street address
- `zip` - for the postal/ZIP code
- `github-id`, `threads-id`, `reddit-id` etc. 

The remainder of the fields should be fairly self-explanatory. I keep just the ID for the person on each social network site instead of the entire URL which could change over time.

See [The Body](person_body.md) to learn about the structure of the rest of the `person.md` template.