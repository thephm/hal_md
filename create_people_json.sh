
#!/bin/bash

#------------------------------------------------------------------------------
#
# Helper script to create a `people.json` file that can be used as a config
# file for tools that use the `message_md`
#
# Goes through every `.md` Markdown file and finds those with frontmatter tag
# `person`. Then
#
# Example:
#
#   People/spongebob
#
#       SpongeBob Squarepants.md
#           ---

#           tags: [person]
#           email: spongebob@gmail.com
#           mobile: 415-555-1212
#           facebook_id: spongybob
#           linkedin_id: spbob
#           ---
#
#   Where:  
#       - `People\spongebob` is the folder
#       - `SpongeBob Squarepants.md` is the person file
#
#   Creates a row:
#
#   {"slug":"spongebob","first-name":"SpongeBob","last-name":"Squarepants","mobile":"415-555-1212","email":"spongebob@gmail.com","facebook-id":"spongybob","linkedin-id":"spbob"},
#
# Notes:
#
#   - this was mostly crafted with the help of ChatGPT
#   - If there's a frontmatter field `slug` use it, not containing folder name
#
#------------------------------------------------------------------------------

# Check if a folder path is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <folder-path>"
    exit 1
fi

folder_path="$1"
output_file="people.json"

echo "[" > "$output_file"

# Find all Markdown files with the .md extension
find "$folder_path" -type f -name "*.md" | while IFS= read -r file; do

    # Extract frontmatter content between "---"
    frontmatter=$(awk '/^---$/ {f = !f; next} f {print}' "$file" | sed '/^---$/d')

    # Extract the part of the filename after the last slash
    folder_slug="${file%/*}"
    folder_slug="${folder_slug##*/}"

    # Check if "tags" frontmatter contains "person"
    if grep -q "^tags:" <<< "$frontmatter" && grep -q "person" <<< "$frontmatter"; then
        # Extract specific fields from YAML frontmatter
        slug=$(echo "$frontmatter" | awk '/^slug:/ {print $2}')
        if [ -z "$slug" ]; then 
            slug=$folder_slug
        fi
        mobile=$(echo "$frontmatter" | awk '/^mobile:/ {print $2}')
        first_name=$(echo "$frontmatter" | awk '/^first_name:/ {print $2}')
        last_name=$(echo "$frontmatter" | awk '/^last_name:/ {print $2}')
        email=$(echo "$frontmatter" | awk '/^email:/ {print $2}')
        facebook_id=$(echo "$frontmatter" | awk '/^facebook_id:/ {print $2}')
        linkedin_id=$(echo "$frontmatter" | awk '/^linkedin_id:/ {print $2}')

        if [ "$mobile" ] || [ "$email" ] || [ "$facebook_id" ] || [ "$linkedin_id" ]; then
            # Create JSON entry for the file
            json_entry="{\"slug\":\"$slug\",\"first-name\":\"$first_name\",\"last-name\":\"$last_name\",\"mobile\":\"$mobile\",\"email\":\"$email\",\"facebook-id\":\"$facebook_id\",\"linkedin-id\":\"$linkedin_id\"}"

            # Append JSON entry to the output file
#            echo "$json_entry,"
            echo "$json_entry," >> "$output_file"
        fi
    fi
done

# Remove the trailing comma and close the JSON array
sed -i '$ s/,$//' "$output_file"
echo "]" >> "$output_file"

echo "JSON data has been written to $output_file"
