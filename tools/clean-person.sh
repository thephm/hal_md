#!/usr/bin/env bash
#
# Markdown Frontmatter Cleanup Script
#
# Purpose:
#   Clean and normalize YAML frontmatter and selected Markdown sections
#   across a directory of Person.md Markdown files.
#
# Usage:
#   ./clean-frontmatter.sh [directory]
#
#   Defaults to the current directory if no directory is specified.
#   Recursively processes .md files, excluding files named YYYY-MM-DD.md.
#
# Frontmatter transformations:
#   - Replace scalar null values with empty values.
#   - Convert inline lists into YAML block-list format.
#   - Split comma-separated list items into separate entries.
#   - Normalize empty lists for aliases, skills, products, and stack
#     to an empty placeholder bullet.
#   - Convert organization fields into a top-level organizations list
#     with an empty bullet, ready for an organization slug.
#
# Markdown body transformations:
#   - Remove the entire ## Interests section, up to the next level-two
#     heading or the end of the file.
#   - Remove the ## Communications section if it contains no content,
#     preserving it when content is present.
#
# Processing:
#   - Modifies files in place only when changes are detected.
#   - Reports updated, unchanged, and total processed file counts.
#   - Warns if no eligible Markdown files are found.
#
# Caution:
#   - Back up files before running.
#   - Organization values are discarded during conversion.
#   - Review the output to ensure list values containing commas have
#     not been split unintentionally.
#

#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"

processed=0
updated=0
unchanged=0

while IFS= read -r -d '' file; do
    processed=$((processed + 1))
    tmp=$(mktemp)

    if awk '
    BEGIN {
        in_frontmatter = 0
        first_line = 1
        in_body = 0
        skip_interests = 0
        in_communications = 0
        communications_has_content = 0
        communications_buffer = ""
    }

    # Detect opening frontmatter fence.
    first_line {
        first_line = 0
        if ($0 == "---") {
            in_frontmatter = 1
        }
        print
        next
    }

    # Detect closing frontmatter fence.
    in_frontmatter && $0 == "---" {
        in_frontmatter = 0
        in_body = 1
        print
        next
    }

    # Frontmatter transformations.
    in_frontmatter {
        # Convert any organization field to a top-level organizations
        # field with an empty placeholder bullet.
        if ($0 ~ /^[[:space:]]*(-[[:space:]]+)?organization:[[:space:]]*/) {
            print "organizations:"
            print "  -"
            next
        }

        # Replace scalar null values with empty values.
        if ($0 ~ /:[[:space:]]*null[[:space:]]*$/) {
            sub(/:[[:space:]]*null[[:space:]]*$/, ": ")
        }

        # Split comma-separated existing list items.
        if ($0 ~ /^[[:space:]]*-[[:space:]]*[^,]+,[[:space:]]*[^,]+/) {
            line = $0
            indent = line
            sub(/-.*/, "", indent)

            value = line
            sub(/^[[:space:]]*-[[:space:]]*/, "", value)

            n = split(value, items, /,[[:space:]]*/)
            for (i = 1; i <= n; i++) {
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", items[i])
                print indent "- " items[i]
            }
            next
        }

        # Convert inline lists to block-list format.
        if ($0 ~ /^[[:space:]]*[[:alnum:]_-]+:[[:space:]]*\[[^][]+\][[:space:]]*$/) {
            line = $0
            key = line
            sub(/:.*/, "", key)

            value = line
            sub(/^[^:]*:[[:space:]]*\[/, "", value)
            sub(/\][[:space:]]*$/, "", value)

            print key ":"

            if (value == "null" || value == "") {
                print "  -"
            } else {
                n = split(value, items, /,[[:space:]]*/)
                for (i = 1; i <= n; i++) {
                    gsub(/^[[:space:]]+|[[:space:]]+$/, "", items[i])
                    if (items[i] == "null" || items[i] == "") {
                        print "  -"
                    } else {
                        print "  - " items[i]
                    }
                }
            }
            next
        }

        # Convert empty lists for specified fields.
        if ($0 ~ /^[[:space:]]*(aliases|skills|products|stack):[[:space:]]*\[[[:space:]]*\][[:space:]]*$/) {
            key = $0
            sub(/:.*/, "", key)
            print key ":"
            print "  -"
            next
        }
    }

    # Body transformations.
    in_body {
        # Remove Interests section up to the next level-two heading.
        if (skip_interests) {
            if ($0 ~ /^## /) {
                skip_interests = 0
            } else {
                next
            }
        }

        if ($0 == "## Interests") {
            skip_interests = 1
            next
        }

        # Buffer Communications to determine whether it is empty.
        if ($0 == "## Communications") {
            in_communications = 1
            communications_heading = $0
            communications_buffer = ""
            communications_has_content = 0
            next
        }

        if (in_communications) {
            if ($0 ~ /^## /) {
                if (communications_has_content) {
                    print communications_heading
                    printf "%s", communications_buffer
                }

                in_communications = 0
                communications_buffer = ""
                print
                next
            }

            communications_buffer = communications_buffer $0 "\n"

            if ($0 ~ /[^[:space:]]/) {
                communications_has_content = 1
            }
            next
        }
    }

    { print }

    END {
        # Preserve Communications at end of file only if it has content.
        if (in_communications && communications_has_content) {
            print communications_heading
            printf "%s", communications_buffer
        }
    }
    ' "$file" > "$tmp"; then
        if ! cmp -s "$file" "$tmp"; then
            cat "$tmp" > "$file"
            echo "UPDATED: $file"
            updated=$((updated + 1))
        else
            unchanged=$((unchanged + 1))
        fi
    else
        echo "ERROR processing: $file" >&2
        rm -f "$tmp"
        exit 1
    fi

    rm -f "$tmp"
done < <(
    find "$ROOT" -regextype posix-extended \
        -type f -name '*.md' \
        ! -regex '.*/[0-9]{4}-[0-9]{2}-[0-9]{2}\.md' \
        -print0
)

echo
echo "Finished."
echo "Files processed: $processed"
echo "Files updated:   $updated"
echo "Files unchanged: $unchanged"

if [[ $processed -eq 0 ]]; then
    echo "WARNING: No Markdown files found. Check directory: $ROOT"
fi