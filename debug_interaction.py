#!/usr/bin/env python3

import os
import sys
sys.path.insert(1, './') 
import communication_file
import md_interactions

def debug_file(file_path):
    """Debug a specific communication file"""
    print(f"Debugging file: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"ERROR: File does not exist: {file_path}")
        return
    
    # Create a communication file object
    comm_file = communication_file.CommunicationFile()
    comm_file.path = file_path
    
    try:
        # Read the frontmatter
        comm_file.frontmatter.read()
        
        print(f"Tags found: {comm_file.frontmatter.tags}")
        print(f"Communication tags: {communication_file.Tags}")
        
        # Check if any tags match communication tags
        matching_tags = [tag for tag in comm_file.frontmatter.tags if tag in communication_file.Tags]
        print(f"Matching communication tags: {matching_tags}")
        
        # Get the date using the same logic as md_interactions
        date_result = md_interactions.get_date(comm_file)
        print(f"get_date() returned: '{date_result}' (type: {type(date_result)})")
        
        # Also check the raw date field
        raw_date = comm_file.frontmatter.date
        print(f"Raw date field: '{raw_date}' (type: {type(raw_date)})")
        
    except Exception as e:
        print(f"ERROR reading file: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Test the specific file
    test_file = r"C:\data\notes\People\crichton-smith\2025-08-30.md"
    debug_file(test_file)