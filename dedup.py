import os
import shutil
import re
import sys
import argparse
import difflib
from collections import defaultdict

def get_backup_path(original_path, base_backup_dir="backups"):
    """Create a backup path mirroring the original structure."""
    abs_path = os.path.abspath(original_path)
    relative_path = os.path.relpath(abs_path, start=os.getcwd())
    return os.path.join(base_backup_dir, relative_path)

def create_backup(original_path, backup_path):
    """Save a backup copy before modifying."""
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    shutil.copy2(original_path, backup_path)

def parse_markdown_content(text):
    """Parse markdown content, preserving frontmatter."""
    # First, identify and preserve frontmatter
    frontmatter = None
    content = text
    
    # Check for YAML frontmatter (between --- markers)
    frontmatter_match = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
    if frontmatter_match:
        frontmatter = frontmatter_match.group(0)
        content = text[len(frontmatter):]
    
    return frontmatter, content

def clean_formatting(text):
    """Clean up the formatting of various email-style markers."""
    # Replace "**-Original Message**-" with "*-- Original Message --*"
    text = re.sub(r'\*\*-+\s*Original\s*Message\s*-+\*\*', '*-- Original Message --*', text, flags=re.IGNORECASE)
    
    # Handle "*-Original Message-*" format (add spacing)
    text = re.sub(r'\*-\s*Original\s*Message\s*-\*', '*-- Original Message --*', text, flags=re.IGNORECASE)
    
    # Also handle other variations of Original Message markers with any combination of - and *
    text = re.sub(r'(\*+|\*+-)[\s-]*Original\s*Message[\s-]*(-\*+|\*+)', '*-- Original Message --*', text, flags=re.IGNORECASE)
    
    # Common email header fields to clean up
    header_fields = ['From', 'To', 'Cc', 'Bcc', 'Subject', 'Date', 'Sent', 'Reply To', 'Reply-To', 'Forwarded']
    
    for field in header_fields:
        # Replace "**Field:** " with "Field: " and ensure there's a newline before it
        text = re.sub(r'(?<!\n)(\*\*' + field + r':\*\*\s)', r'\n' + field + r': ', text)
        text = re.sub(r'(?<=\n)(\*\*' + field + r':\*\*\s)', field + r': ', text)
        
        # Also handle the case where it's already at the start of a line but still has **
        text = re.sub(r'^\*\*' + field + r':\*\*\s', field + r': ', text, flags=re.MULTILINE)
    
    return text

def extract_email_headers(text):
    """Extract email header information from the text."""
    headers = {}
    
    # Common email header fields to extract
    header_fields = {
        'From': r'From:\s*([^\n]+)',
        'To': r'To:\s*([^\n]+)',
        'Subject': r'Subject:\s*([^\n]+)',
        'Date': r'(?:Date|Sent):\s*([^\n]+)'
    }
    
    for field, pattern in header_fields.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            headers[field] = match.group(1).strip()
    
    # Try to extract name from From field
    sender_name = None
    if 'From' in headers:
        # Try to get just the name part from email address
        name_match = re.match(r'([^<]+)(?:<.*>)?', headers['From'])
        if name_match:
            sender_name = name_match.group(1).strip()
    
    headers['sender_name'] = sender_name
    
    return headers

def extract_embeds(text):
    """Extract embedded file references from the text."""
    embeds = []
    
    # Pattern for ![[filename.ext]] and [[filename.ext]] embeds
    embed_pattern = r'(!?\[\[.*?\]\])'
    
    for match in re.finditer(embed_pattern, text):
        embeds.append({
            'text': match.group(0),
            'start': match.start(),
            'end': match.end()
        })
    
    return embeds

def extract_complete_messages(text):
    """Extract complete messages with their headers using multiple patterns."""
    messages = []
    
    # Pattern 1: "Name at HH:MM" format
    pattern1 = r'([A-Za-z]+\s+at\s+\d{1,2}:\d{2})\s*\n((?:.+\n?)+?)(?=\n[A-Za-z]+\s+at\s+\d{1,2}:\d{2}|$)'
    
    # Pattern 2: "Name wrote" or similar formats (possibly with quote markers)
    pattern2 = r'((?:>\s*)?[A-Za-z]+(?:\s+[A-Za-z]+)?\s+wrote(?:(?:\s+\w+){0,5})?(?:\s+on\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})?:)\s*\n((?:.+\n?)+?)(?=\n(?:>\s*)?[A-Za-z]+(?:\s+[A-Za-z]+)?\s+wrote|$)'
    
    # Pattern 3: Just a name followed by blank line then content
    pattern3 = r'((?:>\s*)?(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?))(?:\s*\n\s*\n)((?:.+\n?)+?)(?=\n\n(?:>\s*)?(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)|$)'
    
    # Pattern 4: Email with headers
    pattern4 = r'((?:From|To|Subject|Date|Sent):\s*[^\n]+\n(?:(?:From|To|Cc|Bcc|Subject|Date|Sent|Reply-To):\s*[^\n]+\n)*)\s*\n((?:.+\n?)+?)(?=\n(?:From|To|Subject|Date|Sent):|$)'
    
    # Extract messages using pattern 1
    for match in re.finditer(pattern1, text, re.DOTALL):
        header = match.group(1)
        body = match.group(2).strip()
        messages.append({
            'header': header,
            'body': body,
            'complete_text': f"{header}\n{body}",
            'start': match.start(),
            'end': match.end(),
            'pattern': 'time'
        })
    
    # Extract messages using pattern 2
    for match in re.finditer(pattern2, text, re.DOTALL):
        header = match.group(1)
        body = match.group(2).strip()
        messages.append({
            'header': header,
            'body': body,
            'complete_text': f"{header}\n{body}",
            'start': match.start(),
            'end': match.end(),
            'pattern': 'wrote'
        })
    
    # Extract messages using pattern 3
    for match in re.finditer(pattern3, text, re.DOTALL):
        header = match.group(1)
        body = match.group(2).strip()
        messages.append({
            'header': header,
            'body': body,
            'complete_text': f"{header}\n\n{body}",  # Note the double newline here
            'start': match.start(),
            'end': match.end(),
            'pattern': 'name'
        })
    
    # Extract messages using pattern 4
    for match in re.finditer(pattern4, text, re.DOTALL):
        headers = match.group(1)
        body = match.group(2).strip()
        
        # Extract sender information from headers
        header_info = extract_email_headers(headers)
        messages.append({
            'header': headers,
            'body': body,
            'complete_text': f"{headers}\n{body}",
            'start': match.start(),
            'end': match.end(),
            'pattern': 'email',
            'header_info': header_info
        })
    
    # Sort messages by their position in the text
    messages.sort(key=lambda x: x['start'])
    
    # Remove any overlapping messages (prefer more specific patterns)
    non_overlapping = []
    for msg in messages:
        # Check if this message overlaps with any previously accepted message
        overlaps = False
        for accepted in non_overlapping:
            # If there's significant overlap
            if (msg['start'] < accepted['end'] and msg['end'] > accepted['start']):
                # If patterns conflict, keep the more specific one
                if msg['pattern'] in ['time', 'wrote', 'email'] and accepted['pattern'] == 'name':
                    # Replace the less specific with the more specific
                    non_overlapping.remove(accepted)
                    non_overlapping.append(msg)
                overlaps = True
                break
        
        if not overlaps:
            non_overlapping.append(msg)
    
    return non_overlapping

def has_embed_difference(text1, text2):
    """Check if there are differences in embeds between two texts."""
    # Extract embeds from both texts
    embeds1 = re.findall(r'(!?\[\[.*?\]\])', text1)
    embeds2 = re.findall(r'(!?\[\[.*?\]\])', text2)
    
    # If embed counts differ, they're different
    if len(embeds1) != len(embeds2):
        return True
    
    # Check if all embeds match exactly
    for e1 in embeds1:
        if e1 not in embeds2:
            return True
    
    return False

def create_context_summary(message):
    """Create a context summary for a message that will be removed."""
    if message['pattern'] == 'time':
        # For "Name at HH:MM" format
        name = extract_name_from_header(message['header'])
        if name:
            return f"{name} wrote: [duplicate message removed]"
        return "[duplicate message removed]"
    
    elif message['pattern'] == 'wrote':
        # Keep the "Name wrote:" part
        return f"{message['header']} [duplicate message removed]"
    
    elif message['pattern'] == 'name':
        # For simple name headers
        name = extract_name_from_header(message['header'])
        if name:
            return f"{name} wrote: [duplicate message removed]"
        return "[duplicate message removed]"
    
    elif message['pattern'] == 'email':
        # For email headers, keep a simplified version
        if 'header_info' in message and message['header_info'].get('sender_name'):
            context = f"{message['header_info']['sender_name']} wrote: [duplicate message removed]\n\n"
        else:
            context = "[duplicate message removed]\n\n"
        
        # Add simplified headers
        if 'header_info' in message:
            for field in ['From', 'Sent', 'To', 'Subject']:
                if field in message['header_info']:
                    context += f"{field}: {message['header_info'][field]}\n"
        
        return context
    
    # Default case
    return "[duplicate message removed]"

def find_duplicate_messages(messages, min_chars=40):
    """Find duplicate messages based on content similarity."""
    duplicates = []
    
    # Compare all message pairs
    for i, msg1 in enumerate(messages):
        for j, msg2 in enumerate(messages):
            # Skip self-comparison and already processed messages
            if i >= j:  # This ensures we only compare each pair once and keep the first occurrence
                continue
            
            # First check if there are differences in embeds
            if has_embed_difference(msg1['body'], msg2['body']):
                continue  # Skip this pair if embed differences exist
            
            # Check content similarity even if headers differ
            body_similarity = difflib.SequenceMatcher(None, msg1['body'], msg2['body']).ratio()
            
            # If bodies are very similar and significant in length
            if body_similarity > 0.8 and len(msg2['body']) >= min_chars:
                # Extract name from header for comparison
                name1 = extract_name_from_header(msg1['header'])
                name2 = extract_name_from_header(msg2['header'])
                
                # Higher priority for same sender
                if name1 and name2 and name1.lower() == name2.lower():
                    # Record the complete message for removal
                    context_summary = create_context_summary(msg2)
                    duplicates.append({
                        'text': msg2['complete_text'],
                        'start': msg2['start'],
                        'end': msg2['end'],
                        'similarity': body_similarity,
                        'duplicate_of': i,
                        'same_sender': True,
                        'context_summary': context_summary,
                        'pattern': msg2['pattern']
                    })
                # Also catch duplicates with different senders but mark them differently
                elif body_similarity > 0.9:  # Higher threshold for different senders
                    context_summary = create_context_summary(msg2)
                    duplicates.append({
                        'text': msg2['complete_text'],
                        'start': msg2['start'],
                        'end': msg2['end'],
                        'similarity': body_similarity,
                        'duplicate_of': i,
                        'same_sender': False,
                        'context_summary': context_summary,
                        'pattern': msg2['pattern']
                    })
    
    return duplicates

def extract_name_from_header(header):
    """Extract the sender's name from various header formats."""
    # For "Name at HH:MM" format
    time_match = re.match(r'([A-Za-z]+)\s+at\s+\d{1,2}:\d{2}', header)
    if time_match:
        return time_match.group(1)
    
    # For "Name wrote" or "> Name wrote" formats
    wrote_match = re.match(r'(?:>\s*)?([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+wrote', header)
    if wrote_match:
        return wrote_match.group(1)
    
    # For just a name
    name_match = re.match(r'(?:>\s*)?([A-Za-z]+(?:\s+[A-Za-z]+)?)', header)
    if name_match:
        return name_match.group(1)
    
    # Try to extract from email headers
    from_match = re.search(r'From:\s*([^<\n]+)', header)
    if from_match:
        return from_match.group(1).strip()
    
    # If no pattern matches, return None
    return None

def find_repeating_paragraphs(text, min_chars=40):
    """Find repeating paragraphs that might be duplicates."""
    # Split the content into paragraphs
    paragraphs = re.split(r'\n\s*\n', text)
    
    # Patterns for message headers to ignore
    header_patterns = [
        r'^[A-Za-z]+\s+at\s+\d{1,2}:\d{2}$',
        r'^(?:>\s*)?[A-Za-z]+(?:\s+[A-Za-z]+)?\s+wrote(?:(?:\s+\w+){0,5})?(?:\s+on\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})?:$',
        r'^(?:>\s*)?[A-Za-z]+(?:\s+[A-Za-z]+)?$',  # Just a name
        r'^(?:From|To|Subject|Date|Sent):\s*[^\n]+'  # Email headers
    ]
    
    duplicates = []
    
    for i, para1 in enumerate(paragraphs):
        # Skip headers and short paragraphs
        if any(re.match(pattern, para1.strip()) for pattern in header_patterns) or len(para1) < min_chars:
            continue
            
        for j, para2 in enumerate(paragraphs[i+1:], i+1):
            # Also skip headers and short paragraphs
            if any(re.match(pattern, para2.strip()) for pattern in header_patterns) or len(para2) < min_chars:
                continue
            
            # Check for embed differences
            if has_embed_difference(para1, para2):
                continue  # Skip if there are embed differences
                
            # Check for similar content
            similarity = difflib.SequenceMatcher(None, para1, para2).ratio()
            
            # If paragraphs are very similar
            if similarity > 0.9:
                # Find the position of the duplicate paragraph in the original text
                start_pos = -1
                current_pos = 0
                
                # Find the exact position by advancing through the text
                for k in range(j+1):
                    current_pos = text.find(paragraphs[k], current_pos)
                    if k == j:
                        start_pos = current_pos
                    if current_pos != -1:
                        current_pos += len(paragraphs[k])
                
                if start_pos >= 0:
                    end_pos = start_pos + len(para2)
                    duplicates.append({
                        'text': para2,
                        'start': start_pos,
                        'end': end_pos,
                        'similarity': similarity,
                        'context_summary': "[duplicate content removed]",
                        'pattern': 'paragraph'
                    })
    
    return duplicates

def detect_message_header_before(text, position, max_lines=3):
    """Detect if there's a message header right before the given position."""
    # Get a few lines before the position
    lines_before = text[:position].split('\n')[-max_lines:]
    
    # Patterns for message headers
    header_patterns = [
        r'^[A-Za-z]+\s+at\s+\d{1,2}:\d{2}$',
        r'^(?:>\s*)?[A-Za-z]+(?:\s+[A-Za-z]+)?\s+wrote(?:(?:\s+\w+){0,5})?(?:\s+on\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4})?:$',
        r'^(?:>\s*)?[A-Za-z]+(?:\s+[A-Za-z]+)?$',  # Just a name
        r'^(?:From|To|Subject|Date|Sent):\s*[^\n]+'  # Email headers
    ]
    
    for line in lines_before:
        if any(re.match(pattern, line.strip()) for pattern in header_patterns):
            # Found a header, get its position
            header_pos = text[:position].rfind(line)
            if header_pos >= 0:
                return header_pos, line
    
    return None, None

def remove_duplicates(filepath, interactive=True, min_chars=40, verbose=False, dry_run=False, fix_formatting=True, preserve_context=True):
    """Remove duplicate content while preserving message context."""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()
    
    # Parse frontmatter and content
    frontmatter, content = parse_markdown_content(text)
    
    # Clean up formatting if requested
    if fix_formatting:
        formatted_content = clean_formatting(content)
        formatting_changed = (formatted_content != content)
        content = formatted_content
    else:
        formatting_changed = False
    
    # Extract complete messages
    messages = extract_complete_messages(content)
    if verbose:
        print(f"Found {len(messages)} complete messages")
        for i, msg in enumerate(messages):
            print(f"  Message {i}: {msg['pattern']} pattern")
            if 'header_info' in msg:
                print(f"    Sender: {msg['header_info'].get('sender_name', 'Unknown')}")
            # Show first line of body
            first_line = msg['body'].split('\n')[0] if '\n' in msg['body'] else msg['body']
            print(f"    First line: {first_line}")
    
    # Find embedded file references
    embeds = extract_embeds(content)
    if verbose and embeds:
        print(f"Found {len(embeds)} embedded file references:")
        for embed in embeds:
            print(f"  {embed['text']}")
    
    # Find duplicate messages
    duplicate_messages = find_duplicate_messages(messages, min_chars)
    
    # Also find repeating paragraphs not part of message structure
    duplicate_paragraphs = find_repeating_paragraphs(content, min_chars)
    
    # Combine duplicates
    all_duplicates = duplicate_messages + duplicate_paragraphs
    
    modified = False
    
    # Check if formatting needs to be fixed even if no duplicates
    if fix_formatting and formatting_changed and not all_duplicates:
        modified = True
        if verbose:
            print(f"Fixed formatting in {filepath}")
        
        if not dry_run:
            new_text = frontmatter + content if frontmatter else content
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_text)
        
        return modified
    
    if not all_duplicates:
        if verbose:
            print(f"No duplicates found in {filepath}")
        return modified
    
    print(f"\nFound duplicates in: {filepath}")
    
    # Create backup if not in dry run mode
    if not dry_run:
        backup_path = get_backup_path(filepath)
        create_backup(filepath, backup_path)
        print(f"  Backup created at: {backup_path}")
    
    # Keep track of blocks to remove
    blocks_to_remove = []
    removed_count = 0
    
    if interactive:
        # Sort duplicates by position in the file
        all_duplicates.sort(key=lambda x: x['start'])
        
        for dup in all_duplicates:
            print("\n" + "="*40)
            if 'duplicate_of' in dup:
                if dup.get('same_sender', False):
                    print(f"Duplicate message: {extract_name_from_header(messages[dup['duplicate_of']]['header']) or 'Unknown'} wrote:")
                else:
                    print(f"Similar message from different senders")
            else:
                print(f"Duplicate content ({len(dup['text'])} chars, {dup['similarity']:.2f} similarity):")
            
            # Check if the text contains embeds
            has_embeds = bool(re.search(r'(!?\[\[.*?\]\])', dup['text']))
            if has_embeds:
                print("NOTE: This text contains file embeds.")
            
            print("-"*40)
            print(dup['text'])
            print("="*40)
            
            if preserve_context:
                print(f"Will be replaced with context: {dup['context_summary']}")
            else:
                print("Will be removed completely")
            
            choice = input("Remove this duplicate content? (y/n): ")
            if choice.lower() == "y":
                blocks_to_remove.append(dup)
                removed_count += 1
    else:
        # Auto-remove all duplicates from the same sender (except those with embeds), but prompt for different senders
        for dup in all_duplicates:
            # Skip auto-removal if embeds are present
            has_embeds = bool(re.search(r'(!?\[\[.*?\]\])', dup['text']))
            
            if 'duplicate_of' in dup and dup.get('same_sender', False) and not has_embeds:
                # Auto-remove same-sender duplicates without embeds
                blocks_to_remove.append(dup)
                removed_count += 1
            elif interactive:
                # Prompt for other types of duplicates
                print("\n" + "="*40)
                print(f"Duplicate content ({len(dup['text'])} chars, {dup['similarity']:.2f} similarity):")
                
                if has_embeds:
                    print("NOTE: This text contains file embeds.")
                
                print("-"*40)
                print(dup['text'])
                print("="*40)
                
                if preserve_context:
                    print(f"Will be replaced with context: {dup['context_summary']}")
                else:
                    print("Will be removed completely")
                
                choice = input("Remove this duplicate content? (y/n): ")
                if choice.lower() == "y":
                    blocks_to_remove.append(dup)
                    removed_count += 1
    
    # Only modify the file if we're removing something or fixing formatting, and not in dry run mode
    if (removed_count > 0 or formatting_changed) and not dry_run:
        # Sort blocks by position in reverse order to avoid position changes
        blocks_to_remove.sort(key=lambda x: x['start'], reverse=True)
        
        # Create a new content string by removing the duplicate blocks
        new_content = content
        for block in blocks_to_remove:
            # For duplicates, we need to make sure we include the header if it's not already part of the duplicate
            start_pos = block['start']
            
            # Check if we need to include the header
            if block['pattern'] != 'email':  # Skip for email pattern as it already includes headers
                header_pos, header_line = detect_message_header_before(new_content, start_pos)
                if header_pos is not None and header_pos < start_pos:
                    # The header is right before this content but might not be included in the duplicate range
                    # Adjust the start position to include the header
                    start_pos = header_pos
            
            # Remove the block from content (with header if needed)
            if preserve_context:
                # Replace with context summary instead of completely removing
                new_content = new_content[:start_pos] + block['context_summary'] + '\n\n' + new_content[block['end']:]
            else:
                # Remove completely
                new_content = new_content[:start_pos] + new_content[block['end']:]
        
        # Clean up any excessive newlines
        new_content = re.sub(r'\n{3,}', '\n\n', new_content)
        
        # Reconstruct the document
        if frontmatter:
            new_text = frontmatter + new_content
        else:
            new_text = new_content
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_text)
        
        if removed_count > 0:
            print(f"  Removed {removed_count} duplicate blocks.")
        if formatting_changed and verbose:
            print(f"  Fixed formatting.")
        
        return True
    elif dry_run and (removed_count > 0 or formatting_changed):
        if removed_count > 0:
            print(f"  Would remove {removed_count} duplicate blocks (dry run).")
        if formatting_changed and verbose:
            print(f"  Would fix formatting (dry run).")
        
        return False
    else:
        return modified

def is_dated_markdown_file(filename):
    """Check if the filename matches the YYYY-MM-DD*.md pattern."""
    pattern = r"^\d{4}-\d{2}-\d{2}.*\.md$"
    return bool(re.match(pattern, filename))

def process_folder(folder_path, interactive=True, min_chars=40, verbose=False, dry_run=False, fix_formatting=True, preserve_context=True):
    """Process all dated markdown files in a folder and its subfolders."""
    processed_files = 0
    modified_files = 0
    
    for root, _, files in os.walk(folder_path):
        for file in files:
            if is_dated_markdown_file(file):
                file_path = os.path.join(root, file)
                processed_files += 1
                if remove_duplicates(file_path, interactive, min_chars, verbose, dry_run, fix_formatting, preserve_context):
                    modified_files += 1
    
    action = "Would modify" if dry_run else "Modified"
    print(f"\nSummary: Processed {processed_files} files, {action} {modified_files} files.")

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Remove duplicate content from dated markdown files while preserving message context.")
    parser.add_argument("folder", nargs="?", help="Folder or file path to process")
    parser.add_argument("--auto", action="store_true", help="Automatically remove duplicates from same sender")
    parser.add_argument("--min-chars", type=int, default=40, 
                       help="Minimum content length in characters (default: 40)")
    parser.add_argument("--verbose", action="store_true", help="Show detailed processing information")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be removed without making changes")
    parser.add_argument("--no-format-fix", action="store_true", help="Skip formatting fixes")
    parser.add_argument("--no-context", action="store_true", help="Remove duplicate content completely without leaving context")
    args = parser.parse_args()
    
    # If path is provided as command line argument
    if args.folder:
        if os.path.isdir(args.folder):
            print(f"Starting deduplication process for: {args.folder}")
            print(f"Mode: {'Automatic for same-sender duplicates' if args.auto else 'Interactive'}")
            print(f"Context preservation: {'Off' if args.no_context else 'On'}")
            print(f"Minimum content length: {args.min_chars} characters")
            if args.dry_run:
                print("DRY RUN: No files will be modified")
            if args.no_format_fix:
                print("Skipping formatting fixes")
            process_folder(args.folder, interactive=not args.auto, min_chars=args.min_chars, 
                          verbose=args.verbose, dry_run=args.dry_run, fix_formatting=not args.no_format_fix,
                          preserve_context=not args.no_context)
        elif os.path.isfile(args.folder):
            # Allow processing a single file if provided
            print(f"Processing single file: {args.folder}")
            if args.dry_run:
                print("DRY RUN: No files will be modified")
            if args.no_format_fix:
                print("Skipping formatting fixes")
            remove_duplicates(args.folder, interactive=not args.auto, min_chars=args.min_chars,
                             verbose=args.verbose, dry_run=args.dry_run, fix_formatting=not args.no_format_fix)
        else:
            print(f"Error: '{args.folder}' is not a valid directory or file.")
    # If no arguments provided, prompt for input
    else:
        path = input("Enter file or folder path to deduplicate: ")
        if os.path.isfile(path):
            min_chars = int(input("Minimum content length in characters (default: 40): ") or 40)
            verbose = input("Show verbose output? (y/n): ").lower() == 'y'
            dry_run = input("Dry run (no changes made)? (y/n): ").lower() == 'y'
            fix_formatting = input("Fix message formatting? (y/n): ").lower() == 'y'
            remove_duplicates(path, min_chars=min_chars, verbose=verbose, dry_run=dry_run, fix_formatting=fix_formatting)
        elif os.path.isdir(path):
            min_chars = int(input("Minimum content length in characters (default: 40): ") or 40)
            auto_mode = input("Automatically remove same-sender duplicates? (y/n): ").lower() == 'y'
            verbose = input("Show verbose output? (y/n): ").lower() == 'y'
            dry_run = input("Dry run (no changes made)? (y/n): ").lower() == 'y'
            fix_formatting = input("Fix message formatting? (y/n): ").lower() == 'y'
            process_folder(path, interactive=not auto_mode, min_chars=min_chars, 
                          verbose=verbose, dry_run=dry_run, fix_formatting=fix_formatting)
        else:
            print("File or directory not found.")