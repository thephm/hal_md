# -----------------------------------------------------------------------------
#
# This script merges frontmatter from one Person Markdown file into another.
#
# It reads the frontmatter from the source file and writes it to the target file.
# 
# -----------------------------------------------------------------------------

import os
import sys
import md_person
from argparse import ArgumentParser

# Parse the command line arguments
def get_arguments():

    parser = ArgumentParser()

    parser.add_argument("-s", "--slug", dest="slug", default=".",
                        help="The single slug of the person to merge frontmatter for")

    parser.add_argument("-f", "--from", dest="source", default=".",
                        help="The folder where the source Markdown files are located")

    parser.add_argument("-t", "--target", dest="target", default=".",
                        help="The folder where the target Markdown files are located")

    parser.add_argument("-d", "--debug", dest="debug", action="store_true", default=False,
                        help="Print extra info as the files processed")
    
    parser.add_argument("-x", "--max", type=int, dest="max", default=10000,
                        help="Maximum number of people to merge")

    args = parser.parse_args()

    return args

def merge_frontmatter(from_path, to_path, slug):
    """
    Merge frontmatter from one Person's Markdown file into another.
    
    Parameters:
    from_path (str): Path to the source directory containing person's folder.
    to_path (str): Path to the target directory containing person's folder.
    slug (str): The person's slug (folder name).
    
    Returns:
    dict: Merged frontmatter.
    """
    import yaml
    
    # Read the person's profile file from both directories
    from_person_file = md_person.read_person_frontmatter(slug, from_path)
    to_person_file = md_person.read_person_frontmatter(slug, to_path)
    
    if not from_person_file:
        print(f"Warning: Could not find person profile for {slug} in {from_path}")
        return None
        
    if not to_person_file:
        print(f"Warning: Could not find person profile for {slug} in {to_path}")
        return None
    
    # Parse YAML directly from the raw frontmatter
    from_frontmatter = {}
    to_frontmatter = {}
    
    try:
        # Extract YAML content between --- markers from raw string
        from_raw = from_person_file.frontmatter.raw
        if from_raw and from_raw.count('---') >= 2:
            yaml_content = from_raw.split('---')[1].strip()
            from_frontmatter = yaml.safe_load(yaml_content) or {}
            
        to_raw = to_person_file.frontmatter.raw
        if to_raw and to_raw.count('---') >= 2:
            yaml_content = to_raw.split('---')[1].strip()
            to_frontmatter = yaml.safe_load(yaml_content) or {}
            
    except Exception as e:
        print(f"Error parsing YAML: {e}")
        return None
    
    if args.debug:
        print(f"From frontmatter fields: {from_person_file.frontmatter.fields}")
        print(f"To frontmatter fields: {to_person_file.frontmatter.fields}")
        print(f"From frontmatter values: {from_frontmatter}")
        print(f"To frontmatter values: {to_frontmatter}")
    
    # Merge: source values first, then target values (target preserves existing data)
    merged_frontmatter = {**from_frontmatter, **to_frontmatter}
    
    # Also merge the fields lists
    merged_fields = list(set(to_person_file.frontmatter.fields + from_person_file.frontmatter.fields))
    merged_frontmatter['fields'] = merged_fields
    
    if args.debug:
        print(f"Merged frontmatter fields: {merged_fields}")
        print(f"Merged frontmatter values: {merged_frontmatter}")

    return merged_frontmatter

def write_merged_frontmatter(path, slug, merged_frontmatter):
    """
    Write merged frontmatter to a person's profile file.
    
    Parameters:
    path (str): Path to the directory containing person's folder.
    slug (str): The person's slug (folder name).
    merged_frontmatter (dict): The merged frontmatter dictionary.
    
    Returns:
    bool: True if successful, False otherwise.
    """
    
    # Read the person's profile file
    person_file = md_person.read_person_frontmatter(slug, path)
    
    if not person_file:
        print(f"Error: Could not find person profile for {slug} in {path}")
        return False
    
    # Read the body to preserve it
    person_file.body.read()
    
    # Handle the fields list specially
    if 'fields' in merged_frontmatter:
        person_file.frontmatter.fields = merged_frontmatter['fields']
        if args.debug:
            print(f"Set fields list to: {person_file.frontmatter.fields}")
    
    # Update frontmatter fields with merged values
    for field, value in merged_frontmatter.items():
        # Skip internal attributes and the fields list (already handled)
        if field.startswith('_') or field == 'fields':
            if args.debug and field.startswith('_'):
                print(f"Skipping internal field: {field}")
            continue
        
        if args.debug:
            print(f"Setting field '{field}' to value '{value}'")
            
        # Add field to fields list if not already there
        if field not in person_file.frontmatter.fields:
            person_file.frontmatter.fields.append(field)
            if args.debug:
                print(f"Added '{field}' to fields list")
        else:
            if args.debug:
                print(f"Field '{field}' already in fields list")
            
        # Set the attribute on the correct object based on YAML_TO_ATTR mapping
        # Check if this field needs to be set on a subobject
        if hasattr(md_person, 'YAML_TO_ATTR') and field in md_person.YAML_TO_ATTR:
            path_tuple = md_person.YAML_TO_ATTR[field]
            obj = person_file
            
            # Navigate to the correct subobject
            for attr in path_tuple[:-1]:
                if attr:  # Skip empty strings in the path
                    obj = getattr(obj, attr, None)
                    if obj is None:
                        if args.debug:
                            print(f"Warning: Could not navigate to {attr} for field {field}")
                        break
            
            if obj is not None:
                setattr(obj, path_tuple[-1], value)
                if args.debug:
                    print(f"Set {field} on {'.'.join([x for x in path_tuple if x])}")
            else:
                # Fallback to setting on frontmatter directly
                setattr(person_file.frontmatter, field, value)
                if args.debug:
                    print(f"Fallback: Set {field} directly on frontmatter")
        else:
            # Set directly on the frontmatter object
            setattr(person_file.frontmatter, field, value)
            if args.debug:
                print(f"Set {field} directly on frontmatter")
    
    if args.debug:
        print(f"Final fields for {slug}: {person_file.frontmatter.fields}")
        print(f"Final frontmatter dict: {person_file.frontmatter.__dict__}")
    
    # Save the file
    try:
        if args.debug:
            print(f"About to save file. Checking field values before save:")
            for field in person_file.frontmatter.fields:
                value = getattr(person_file.frontmatter, field, None)
                print(f"  {field}: {repr(value)} (type: {type(value)})")
            
            # Check what get_yaml() will generate
            try:
                yaml_output = person_file.get_yaml()
                print(f"Generated YAML output:")
                print(yaml_output)
            except Exception as e:
                print(f"Error generating YAML: {e}")
        
        result = person_file.save()
        if result:
            print(f"Successfully updated frontmatter for {slug}")
        return result
    except Exception as e:
        print(f"Error saving file for {slug}: {e}")
        return False

def do_merge(from_path, to_path, max_people, from_slugs, to_slugs, specific_slug=None):
    """
    Merge frontmatter from each Person Markdown file into the corresponding target file.

    Parameters:
    from_path (str): Path to the source directory containing Markdown files.
    to_path (str): Path to the target directory containing Markdown files.
    max_people (int): Maximum number of people to process.
    from_slugs (list): List of slugs in the source directory.
    to_slugs (list): List of slugs in the target directory.
    specific_slug (str): If provided, only process this specific slug.
    
    Returns:
    dict: Merged frontmatter.
    """
    processed_count = 0
    
    # If a specific slug is provided, only process that one
    if specific_slug:
        slugs_to_process = [specific_slug]
    else:
        slugs_to_process = from_slugs
    
    for slug in slugs_to_process:
        if args.debug:
            print(f"Processing slug: {slug}")
            
        if not specific_slug and processed_count >= max_people:
            print(f"Reached maximum limit of {max_people} people. Stopping.")
            break
            
        if slug in to_slugs:
            print(f"Merging frontmatter for {slug} from {from_path} to {to_path}.")
            merged_frontmatter = merge_frontmatter(from_path, to_path, slug)
            if merged_frontmatter:
                write_merged_frontmatter(to_path, slug, merged_frontmatter)
            processed_count += 1
        else:
            print(f"Skipping {slug} as it doesn't exists in the target path")
            continue

args = get_arguments()
from_path = args.source
to_path = args.target
if args.debug:
    print(f"Source path: {from_path}")
    print(f"Target path: {to_path}")

if not from_path or not to_path:
    print("Source and target paths must be specified.")
    sys.exit(1) 

if not os.path.exists(from_path):
    print(f"Error: Source path does not exist: {from_path}")
    sys.exit(1)
    
if not os.path.exists(to_path):
    print(f"Error: Target path does not exist: {to_path}")
    sys.exit(1)

# Check if a specific slug was provided
specific_slug = args.slug if args.slug != "." else None

if specific_slug:
    print(f"Processing specific slug: {specific_slug}")
    
    # For specific slug, just check if the directories exist instead of getting all slugs
    source_slug_path = os.path.join(from_path, specific_slug)
    target_slug_path = os.path.join(to_path, specific_slug)
    
    if not os.path.exists(source_slug_path):
        print(f"Error: Slug '{specific_slug}' not found in source directory: {source_slug_path}")
        sys.exit(1)
        
    if not os.path.exists(target_slug_path):
        print(f"Error: Slug '{specific_slug}' not found in target directory: {target_slug_path}")
        sys.exit(1)
    
    # Create minimal slug lists for the specific slug
    from_slugs = [specific_slug]
    to_slugs = [specific_slug]
    
    do_merge(from_path, to_path, args.max, from_slugs, to_slugs, specific_slug)
else:
    print(f"Processing up to {args.max} slugs")
    
    if args.debug:
        print("Checking source path contents...")
        
    from_slugs = md_person.get_slugs(from_path)

    if args.debug:
        print("Checking target path contents...")
        
    to_slugs = md_person.get_slugs(to_path)

    if args.debug:
        print(f"Found {len(from_slugs)} slugs in source: {from_slugs}")
        print(f"Found {len(to_slugs)} slugs in target: {to_slugs}")
    
    do_merge(from_path, to_path, args.max, from_slugs, to_slugs)
