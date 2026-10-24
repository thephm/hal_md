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
#   Recursively processes .md files, excluding filenames starting YYYY-MM-DD.
#
# Frontmatter transformations:
#   - Clear scalar None/null values and remove None/null list items.
#   - Convert inline lists into YAML block-list format.
#   - Split comma-separated list items into separate entries.
#   - Normalize empty lists for aliases, skills, products, and stack
#     to an empty placeholder bullet.
#   - Convert organization fields into a top-level organizations list
#     with an empty bullet, ready for an organization slug.
#   - Ensure a blank line separates the closing frontmatter fence from an H1.
#
# Markdown body transformations:
#   - Convert fenced descriptions under Positions headings to blockquotes.
#   - Remove the entire ## Interests section, up to the next level-two
#     heading or the end of the file.
#   - Remove ## Quotes when it contains only blank lines or bare quote markers.
#   - Add a blank line and an empty list item to empty ## Notes sections.
#   - Normalize spacing around H1-H3 headings and blockquote blocks.
#   - Remove empty quoted lines at the start or end of blockquote blocks.
#   - Flatten quoted -, *, and • bullets, including wrapped lines, into one
#     paragraph with period separators.
#   - Remove standalone quoted Responsibilities/Responsabilities/Achievements labels.
#   - Remove LinkedIn recommendation summaries and ranked names from Positions.
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
        after_frontmatter = 0
        in_positions = 0
        in_position_code = 0
        skip_interests = 0
        in_notes = 0
        notes_has_content = 0
        notes_buffer = ""
        in_quotes = 0
        quotes_has_content = 0
        quotes_buffer = ""
        in_communications = 0
        communications_has_content = 0
        communications_buffer = ""
    }

    # Detect opening frontmatter fence.
    first_line {
        first_line = 0
        fence = $0
        sub(/\r$/, "", fence)
        if (fence == "---") {
            in_frontmatter = 1
        }
        print
        next
    }

    # Detect closing frontmatter fence.
    in_frontmatter {
        fence = $0
        sub(/\r$/, "", fence)
    }

    in_frontmatter && fence == "---" {
        in_frontmatter = 0
        in_body = 1
        after_frontmatter = 1
        print
        next
    }

    after_frontmatter {
        after_frontmatter = 0
        if ($0 ~ /^#[[:space:]]/) {
            print ($0 ~ /\r$/ ? "\r" : "")
        }
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

        # Replace scalar None/null values with empty values.
        if ($0 ~ /:[[:space:]]*([Nn][Oo][Nn][Ee]|[Nn][Uu][Ll][Ll])[[:space:]]*$/) {
            sub(/:[[:space:]]*([Nn][Oo][Nn][Ee]|[Nn][Uu][Ll][Ll])[[:space:]]*$/, ": ")
        }

        # Remove list entries whose value is None/null.
        if ($0 ~ /^[[:space:]]*-[[:space:]]*([Nn][Oo][Nn][Ee]|[Nn][Uu][Ll][Ll])[[:space:]]*$/) {
            next
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

            if (tolower(value) == "null" || tolower(value) == "none" || value == "") {
                print "  -"
            } else {
                n = split(value, items, /,[[:space:]]*/)
                valid_items = 0
                for (i = 1; i <= n; i++) {
                    gsub(/^[[:space:]]+|[[:space:]]+$/, "", items[i])
                    if (tolower(items[i]) != "null" && tolower(items[i]) != "none" && items[i] != "") {
                        print "  - " items[i]
                        valid_items++
                    }
                }
                if (valid_items == 0) {
                    print "  -"
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
        line = $0
        sub(/\r$/, "", line)

        if (in_position_code) {
            if (line ~ /^```/) {
                in_position_code = 0
            } else {
                print "  > " $0
            }
            next
        }

        if (tolower(line) ~ /^#{1,3}[[:space:]]+positions[[:space:]]*$/) {
            in_positions = 1
        } else if (line ~ /^## /) {
            in_positions = 0
        }

        if (in_positions && line ~ /^```/) {
            in_position_code = 1
            next
        }

        # Add a ready-to-fill list item to empty Notes sections.
        if (in_notes) {
            if (line ~ /^## /) {
                print notes_heading
                if (notes_has_content) {
                    printf "%s", notes_buffer
                } else {
                    printf "%s- %s", notes_eol, notes_eol
                }

                in_notes = 0
                notes_buffer = ""
                notes_has_content = 0
            } else {
                notes_buffer = notes_buffer $0 "\n"
                if (line ~ /[^[:space:]]/ && line !~ /^[[:space:]]*-[[:space:]]*$/) {
                    notes_has_content = 1
                }
                next
            }
        }

        if (line == "## Notes") {
            in_notes = 1
            notes_heading = $0
            notes_eol = ($0 ~ /\r$/ ? "\r\n" : "\n")
            notes_buffer = ""
            notes_has_content = 0
            next
        }

        # Remove Quotes sections that contain only blank lines or bare quote markers.
        if (in_quotes) {
            if (line ~ /^## /) {
                if (quotes_has_content) {
                    print quotes_heading
                    printf "%s", quotes_buffer
                }

                in_quotes = 0
                quotes_buffer = ""
                quotes_has_content = 0
            } else {
                quotes_buffer = quotes_buffer $0 "\n"
                if (line ~ /[^[:space:]]/ && line !~ /^[[:space:]]*>[[:space:]]*$/) {
                    quotes_has_content = 1
                }
                next
            }
        }

        if (line == "## Quotes") {
            in_quotes = 1
            quotes_heading = $0
            quotes_buffer = ""
            quotes_has_content = 0
            next
        }

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
        # Retain Notes at end of file and add a placeholder if it is empty.
        if (in_notes) {
            print notes_heading
            if (notes_has_content) {
                printf "%s", notes_buffer
            } else {
                printf "%s- %s", notes_eol, notes_eol
            }
        }

        # Preserve Quotes at end of file only if it has meaningful content.
        if (in_quotes && quotes_has_content) {
            print quotes_heading
            printf "%s", quotes_buffer
        }

        # Preserve Communications at end of file only if it has content.
        if (in_communications && communications_has_content) {
            print communications_heading
            printf "%s", communications_buffer
        }
    }
    ' "$file" | awk '
    function text(line) {
        sub(/\r$/, "", line)
        return line
    }

    {
        line = text($0)

        if (NR == 1 && line == "---") {
            in_frontmatter = 1
            print
            next
        }

        if (in_frontmatter) {
            print
            if (line == "---") {
                in_frontmatter = 0
            }
            next
        }

        if (tolower(line) ~ /^[[:space:]]*>[[:space:]]*(main[[:space:]]+)?(responsibilities|responsabilities|achievements):?[[:space:]]*$/) {
            next
        }

        if (line == "## Positions") {
            in_positions = 1
        } else if (line ~ /^## /) {
            in_positions = 0
        }

        if (remove_recommendations) {
            if (line ~ /^## /) {
                remove_recommendations = 0
            } else if (line ~ /^[[:space:]]*>[[:space:]]*$/ ||
                       tolower(line) ~ /^[[:space:]]*>[[:space:]]*[0-9]+(st|nd|rd|th)[[:space:]]+[^[:space:]].*$/) {
                next
            } else {
                remove_recommendations = 0
            }
        }

        if (in_positions &&
            tolower(line) ~ /^[[:space:]]*>[[:space:]].*[[:space:]]has[[:space:]]+[0-9]+[[:space:]]+recommendations[[:space:]]+\([^)]*\)[[:space:]]+including:[[:space:]]*$/) {
            remove_recommendations = 1
            next
        }

        print
    }
    ' | awk '
    function text(line) {
        sub(/\r$/, "", line)
        return line
    }

    function is_bullet_quote(idx, line) {
        line = text(raw_lines[idx])
        return raw_quote[idx] && line ~ /^[[:space:]]*>[[:space:]]*(-|•|\*)[[:space:]]*/
    }

    function bullet_text(idx, line) {
        line = text(raw_lines[idx])
        sub(/^[[:space:]]*>[[:space:]]*/, "", line)
        sub(/^(-|•|\*)[[:space:]]*/, "", line)
        sub(/[[:space:]]+$/, "", line)
        return line
    }

    function sentence(text) {
        sub(/[[:space:]]+$/, "", text)
        if (text !~ /[.!?]$/) {
            text = text "."
        }
        return text
    }

    function append_bullet(result, item) {
        if (item != "") {
            result = result (result == "" ? "" : " ") sentence(item)
        }
        return result
    }

    {
        raw_lines[NR] = $0
        clean = text($0)

        if (NR == 1 && clean == "---") {
            in_frontmatter = 1
            next
        }

        if (in_frontmatter) {
            if (clean == "---") {
                in_frontmatter = 0
            }
            next
        }

        if (in_code) {
            if (clean ~ /^[[:space:]]*(```|~~~)/) {
                in_code = 0
            }
            next
        }

        if (clean ~ /^[[:space:]]*(```|~~~)/) {
            in_code = 1
            next
        }

        if (clean ~ /^#{1,3}[[:space:]]/) {
            raw_special[NR] = 1
        } else if (clean ~ /^[[:space:]]*>/) {
            raw_special[NR] = 1
            raw_quote[NR] = 1
            if (clean ~ /^[[:space:]]*>[[:space:]]*$/) {
                raw_quote_blank[NR] = 1
            }
        }
    }

    END {
        total = 0
        for (i = 1; i <= NR;) {
            if (is_bullet_quote(i)) {
                first = i
                last = i
                current_item = bullet_text(i)
                joined = ""
                j = i + 1

                while (j <= NR && raw_quote[j]) {
                    if (is_bullet_quote(j)) {
                        joined = append_bullet(joined, current_item)
                        current_item = bullet_text(j)
                        last = j
                        j++
                    } else if (raw_quote_blank[j]) {
                        last = j
                        j++
                    } else {
                        continuation = text(raw_lines[j])
                        sub(/^[[:space:]]*>[[:space:]]*/, "", continuation)
                        sub(/^[[:space:]]+/, "", continuation)
                        sub(/[[:space:]]+$/, "", continuation)
                        if (continuation != "") {
                            current_item = current_item (current_item == "" ? "" : " ") continuation
                        }
                        last = j
                        j++
                    }
                }
                joined = append_bullet(joined, current_item)

                prefix = text(raw_lines[first])
                sub(/>.*/, "", prefix)
                total++
                lines[total] = prefix "> " joined (raw_lines[first] ~ /\r$/ ? "\r" : "")
                special[total] = 1
                quote[total] = 1
                i = last + 1
            } else {
                total++
                lines[total] = raw_lines[i]
                special[total] = raw_special[i]
                quote[total] = raw_quote[i]
                quote_blank[total] = raw_quote_blank[i]
                i++
            }
        }

        eol = (lines[1] ~ /\r$/ ? "\r" : "")
        previous = 0
        pending_blanks = 0

        for (i = 1; i <= total;) {
            if (!quote[i]) {
                i++
                continue
            }

            start = i
            first_content = 0
            last_content = 0
            while (i <= total && quote[i]) {
                if (!quote_blank[i]) {
                    if (!first_content) {
                        first_content = i
                    }
                    last_content = i
                }
                i++
            }

            if (first_content) {
                for (j = first_content; j <= last_content; j++) {
                    if (quote_blank[j]) {
                        keep_quote_blank[j] = 1
                    }
                }
            }
        }

        for (i = 1; i <= total; i++) {
            if (quote_blank[i] && !keep_quote_blank[i]) {
                continue
            }

            clean = text(lines[i])
            if (clean ~ /^[[:space:]]*$/) {
                if (previous) {
                    pending_blanks++
                } else {
                    print lines[i]
                }
                continue
            }

            if (previous) {
                if (special[previous] || special[i]) {
                    if (!(quote[previous] && quote[i] && pending_blanks == 0)) {
                        print eol
                    }
                } else {
                    for (j = 0; j < pending_blanks; j++) {
                        print lines[previous + j + 1]
                    }
                }
            }

            print lines[i]
            previous = i
            pending_blanks = 0
        }

        if (previous && pending_blanks) {
            if (special[previous]) {
                print eol
            } else {
                for (j = 0; j < pending_blanks; j++) {
                    print lines[previous + j + 1]
                }
            }
        }
    }
    ' > "$tmp"; then
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
        ! -regex '.*/[0-9]{4}-[0-9]{2}-[0-9]{2}.*\.md' \
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