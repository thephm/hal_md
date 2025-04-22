#!/usr/bin/env python3

# Created with ChatGPT
#
# This script extracts frontmatter from markdown files in a given folder and 
# generates a JSON file with person information. It assumes that the 
# frontmatter is in YAML format and contains specific fields.
#
# It also assumes that the folder structure is such that each person's markdown
# file is in a subfolder named after the person's slug.
# 
# The script uses the PyYAML library to parse the YAML frontmatter.
# 
# To run it, the PyYAML library needs to be installed. To install it using pip:
# 
# pip install pyyaml

import os
import sys
import json
import yaml

def extract_frontmatter(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    if not lines or not lines[0].strip() == '---':
        return None  # No frontmatter

    # Extract YAML block between --- and ---
    try:
        end_index = lines[1:].index('---\n') + 1
    except ValueError:
        return None  # Malformed frontmatter

    frontmatter_lines = lines[1:end_index]
    yaml_text = ''.join(frontmatter_lines)
    try:
        parsed_yaml = yaml.safe_load(yaml_text)
        if not isinstance(parsed_yaml, dict):
            print(f"Invalid YAML structure in file {filepath}: Expected a dictionary but got {type(parsed_yaml).__name__}")
            return None
        return parsed_yaml
    except yaml.YAMLError as e:
        print(f"Error parsing YAML in file {filepath}: {e}")
        return None
    except ValueError as e:
        print(f"Invalid date or value in YAML in file {filepath}: {e}")
        return None
    
def clean_field(value):
    return value if value is not None else ""

def extract_emails(frontmatter):
    # List of all possible email keys in order
    email_keys = ['email', 'work_email', 'home_email', 'other_email']
    emails = [frontmatter.get(key) for key in email_keys if frontmatter.get(key)]
    return ";".join(emails)

def update_person_file(filepath, slug):
    """Update the person's markdown file to include the slug in the frontmatter."""
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    if not lines or not lines[0].strip() == '---':
        print(f"Warning: File {filepath} does not have valid frontmatter. Skipping update.")
        return

    try:
        end_index = lines[1:].index('---\n') + 1
    except ValueError:
        print(f"Warning: Malformed frontmatter in file {filepath}. Skipping update.")
        return

    # Check if the slug already exists in the frontmatter
    for i in range(1, end_index):
        if lines[i].strip().startswith('slug:'):
            return

    # Insert the slug after the last_name field in the frontmatter
    for i in range(1, end_index):
        if lines[i].strip().startswith('last_name:'):
            lines.insert(i + 1, f"slug: {slug}\n")
            break
    else:
        lines.insert(end_index, f"slug: {slug}\n")

    # Write the updated content back to the file
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"Added slug: {slug} to file {filepath}")

def extract_person_info(frontmatter, folder_slug, filepath):
    tags = frontmatter.get('tags')
    if tags is None:
        tags = []  # Default to an empty list if 'tags' is None
    elif isinstance(tags, str):
        tags = [t.strip() for t in tags.strip('[]').split(',')]  # Convert string to list if needed

    if 'person' not in tags:
        return None

    slug = frontmatter.get('slug')
    if not slug:
        slug = folder_slug
        update_person_file(filepath, slug)  # Update the file with the generated slug

    return {
        "slug": slug,
        "first-name": clean_field(frontmatter.get('first_name')),
        "last-name": clean_field(frontmatter.get('last_name')),
        "mobile": clean_field(frontmatter.get('mobile')),
        "work-mobile": clean_field(frontmatter.get('work_mobile')),
        "email": extract_emails(frontmatter),
        "facebook-id": clean_field(frontmatter.get('facebook_id')),
        "linkedin-id": clean_field(frontmatter.get('linkedin_id')),
        "x-id": clean_field(frontmatter.get('x_id'))
    }

def main(folder_path):
    people = []
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.endswith('.md'):
                full_path = os.path.join(root, file)
                folder_slug = os.path.basename(os.path.dirname(full_path))
                frontmatter = extract_frontmatter(full_path)
                if frontmatter:
                    person = extract_person_info(frontmatter, folder_slug, full_path)
                    if person:
                        people.append(person)

    with open('people.json', 'w', encoding='utf-8') as f:
        json.dump(people, f, indent=2)

    print("JSON data has been written to people.json")

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python generate_people_json.py <folder-path>")
        sys.exit(1)
    main(sys.argv[1])
