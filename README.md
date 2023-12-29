# hal_md

Personal relationship management of your ego social network using plain-text Markdown files. Think of it like a Personal CRM on steroids.

At this point, mostly a collection of templates but over tine could evolve. Relies heavily on a Personal Knowledge Management (PKM) tool like Obsidian but also could be useful with any text editor.

## Context

Getting here has been a decades-long journey which you can read about in [The Long and Winding Road](docs/journey.md).

## Navigating your social network

You can use any text editor but preferably one that supports wikilinks, YAML frontmatter, and queries.

1. [Obsidian](https://obsidian.md/) by fellow Canadians [Erica Xu](https://github.com/ericaxu) and [Shida Li](https://github.com/lishid)
2. [Silver Bullet](https://github.com/silverbulletmd) which is Open-Source by Polish [Zef Hemel](https://github.com/zefhemel)

Obsidian has a graph view (aka Map of Content aka MoC) which is fun to visualize your social network. Visual Studio Code is handy as well.

## Helper tools

I've written some Python tools to convert exports from various messaging apps to Markdown. So far, I've done LinkedIn ([linkedin_md](https://github.com/thephm/linkedin_md)), Signal ([signal_md](https://github.com/thephm/signal_md)), and SMS Backup ([sms_backup_md](https://github.com/thephm/sms_backup_md)). Why? So I can get **my** conversations with people in **my** network into **my** own files that **I** can control and use directly with **my** social network data. Each of those tools rely on [message_md](https://github.com/thephm/message_md).

## How it works

There is no real software (yet?), mostly Obsidian templates and some instructions.

## Templates

There are a set of templates I use to track my social network. Each contain a set of metadata at the top also known as YAML frontmatter.

File | For what | Notes
---|---|---
[Call.md](templates/Call.md) | phone calls | Do people still make these?
[Chat.md](templates/Chat.md) | instant messaging chat | e.g. LinkedIn, Signal
[Organization.md](templates/Organization.md) | for schools and companies | Where a `Person` studie, volunteers, or works
[Place.md](templates/Place.md) | a physical place | may link to People in form of `[personA, personB]`
[Post.md](templates/Post.md) | a social media  | Material post by a `Person` 
[Product.md](templates/Product.md)| products | List of product slugs in `[]` worked on by a `Person` and/or `Organization`
[Video.md](templates/Video.md) |  videos | e.g. YouTube video by `People`
