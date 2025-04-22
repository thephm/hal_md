# The `hal_md` and related scripts are part of a larger project that involves
# generating and managing a collection of Markdown files. The scripts use a 
# `people.json` file as input to determine the person slug associated with 
# phone numbers and email addresses. 
#
# This script is temporary to help me update my people Markdown files with 
# current contact info (email addresses, mobile phone numbers). And also to
# remove old values that are no longer valid and update the JSON file with
# them for archival purposes. 
# 
# It compares two JSON files that are lists of dictionaries representing a 
# person. Each dictionary has a unique "slug" key. Typically, the slug is 
# `firstname_lastname`.
#
# I have oodles of people Markdown files and a `create_people_json.py` script 
# that generates a JSON file with all of the people based on the frontmatter 
# in each person's file. 
#  
# I need to compare the generated JSON file with the `people.json` to see if
# there are any new or changed values. I then manually (yeah, I know), update
# the original People Markdown files with the new values.
#
# Why not update the original Markdown files and just use them instead of this
# chaos? Because I have a lot of Markdown files and I don't want to break them.
# I want to keep the original files intact and just update the JSON file. Also
# because I developed the scripts at different times. Lastly, the `people.json`
# supports multiple phone numbers and email addresses, many of which are old
# and no longer valid. I want to keep the old values in the JSON file for 
# archival purposes when I process old emails for example. I don't want or
# need those old values in the Markdown files that I use every day.
#
# Phew, that was a lot of background but I needed to write it down to get it 
# out of my head.

# The script compares two JSON files, identifies conflicts or missing records, 
# and allows you to choose between keeping the original or using the modified 
# version for conflicting records. It also identifies records that exist in the
# original file but are missing in the modified file.
# 
# When a record exists in both files but has differences, the script shows the 
# differences using show_diff_dicts. You are prompted to choose between:
#
#    [o] Keep original: Keeps the record from the original file.
#    [m] Use modified: Uses the record from the modified file updating the original.

import json
import difflib

def load_json_list(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

def normalize_dict(d):
    """Remove fields that are blank (None, empty string, empty list) and ensure consistent structure."""
    if not isinstance(d, dict):
        return d  # Return as-is if not a dictionary
    return {k: normalize_dict(v) for k, v in d.items() if v not in (None, "", [], {})}

def to_dict_by_slug(items):
    slug_dict = {}
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            print(f"⚠️ Skipping non-dict item at index {i}: {item}")
            continue

        slug = item.get("slug")
        if not isinstance(slug, str):
            print(f"⚠️ Skipping item at index {i} with invalid slug (type={type(slug).__name__}):\n{json.dumps(item, indent=2)}")
            continue

        slug_dict[slug] = item
    return slug_dict

def show_diff_dicts(orig, mod):
    # Normalize the dictionaries to ignore blank and missing fields
    orig_normalized = normalize_dict(orig)
    mod_normalized = normalize_dict(mod)

    # Ensure consistent formatting for comparison
    orig_lines = json.dumps(orig_normalized, indent=2, ensure_ascii=False).splitlines()
    mod_lines = json.dumps(mod_normalized, indent=2, ensure_ascii=False).splitlines()

    diff = difflib.unified_diff(
        orig_lines, mod_lines, fromfile="original", tofile="modified", lineterm=""
    )
    return "\n".join(diff)

def choose_version(slug, orig, mod):
    # Normalize the dictionaries to ignore blank and missing fields
    orig_normalized = normalize_dict(orig)
    mod_normalized = normalize_dict(mod)

    # Handle the email field specifically
    orig_emails = set(orig.get("email", "").split(";")) if orig else set()
    mod_email = mod.get("email", "").strip() if mod else ""

    if mod_email and mod_email not in orig_emails:
        orig_emails.add(mod_email)
        orig["email"] = ";".join(sorted(orig_emails))  # Merge emails and sort for consistency

    # Compare the rest of the fields
    orig_normalized = normalize_dict(orig)
    mod_normalized = normalize_dict(mod)

    print(f"\n=== Conflict for slug: {slug} ===")
    print(show_diff_dicts(orig_normalized, mod_normalized))
    print("\nChoose:")
    print("[o] Keep original")
    print("[m] Use modified")
    choice = input("Choice [o/m]? ").strip().lower()

    if choice == "o":
        return orig
    elif choice == "m":
        return mod
    else:
        print("Invalid input, defaulting to original.")
        return orig
    
def show_diff_dicts(orig, mod):
    # Normalize the dictionaries to ignore blank and missing fields
    orig_normalized = normalize_dict(orig)
    mod_normalized = normalize_dict(mod)

    # Ensure consistent formatting for comparison
    orig_lines = json.dumps(orig_normalized, indent=2, ensure_ascii=False).splitlines()
    mod_lines = json.dumps(mod_normalized, indent=2, ensure_ascii=False).splitlines()

    diff = difflib.unified_diff(
        orig_lines, mod_lines, fromfile="original", tofile="modified", lineterm=""
    )
    return "\n".join(diff)

def main(original_file, modified_file):
    original_list = load_json_list(original_file)
    modified_list = load_json_list(modified_file)

    orig_dict = to_dict_by_slug(original_list)
    mod_dict = to_dict_by_slug(modified_list)

    all_slugs = sorted(set(orig_dict) | set(mod_dict))

    missing_records = []

    for slug in all_slugs:
        orig = orig_dict.get(slug)
        mod = mod_dict.get(slug)

        # Normalize both records before comparison
        orig_normalized = normalize_dict(orig) if orig else None
        mod_normalized = normalize_dict(mod) if mod else None

        # Compare normalized records for conflict detection
        if orig_normalized and mod_normalized:
            if orig_normalized != mod_normalized:
                # Display the conflict only once
                updated_record = choose_version(slug, orig, mod)
                missing_records.append(updated_record)
        elif orig_normalized:  # Record exists in original but not in modified
            print(f"\n+++ Missing record in modified: {slug}")
            print(json.dumps(orig_normalized, indent=2, ensure_ascii=False))
            missing_records.append(orig_normalized)

    print(f"\n✅ Found {len(missing_records)} missing or conflicting records.")
    print("You can save these records to a separate file if needed.")
    
if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python compare_by_slug.py original.json modified.json")
    else:
        main(sys.argv[1], sys.argv[2])
