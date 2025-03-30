# dedup.py - Markdown File Deduplication Tool

A Python utility for removing duplicate content from markdown files while preserving context, with special handling for email threads and conversation logs.

*DISCLAIMER: This tool was written using ChatGPT and Claude. It is destructive so suggest creating copies of your files and using it on those, not on your original files.*

## Overview

`dedup.py` is designed to clean up markdown files containing email threads, conversations, or notes that often contain duplicate content. It identifies and removes redundant information while preserving the context and structure of the original document.

## Features

- **Smart Duplicate Detection**: Identifies duplicate messages and paragraphs with content similarity analysis
- **Context Preservation**: Optionally replaces duplicates with contextual markers rather than removing completely
- **Batch Processing**: Groups similar duplicates to reduce the number of interactions
- **Customizable Replacement**: Prompts for replacement text for each duplicate or group
- **Selective Processing**: Interactive mode allows reviewing each duplicate or group
- **Robust Error Handling**: Gracefully handles missing files, permission issues, and interruptions
- **Backup Creation**: Automatically creates backups before modifying files
- **Formatting Fixes**: Optionally cleans up common email formatting issues

## Installation

1. Ensure you have Python 3.6+ installed
2. Download `dedup.py` to your preferred location
3. No external dependencies required (uses Python standard library only)

## Usage

### Basic Usage

```bash
python dedup.py <folder_or_file_path>
```

This will process all dated markdown files (format: YYYY-MM-DD*.md) in the specified folder and its subfolders interactively.

### Command Line Arguments

```bash
python dedup.py [options] <folder_or_file_path>
```

Options:
- `--auto`: Automatically remove duplicates from the same sender without prompting
- `--min-chars INT`: Minimum content length in characters to consider for deduplication (default: 40)
- `--verbose`: Show detailed processing information
- `--dry-run`: Show what would be removed without making changes
- `--no-format-fix`: Skip formatting fixes
- `--no-prompt`: Don't prompt for replacement text (just remove duplicates)
- `--no-context`: Remove duplicate content completely without leaving context

### Interactive Mode

When run in interactive mode, the tool will:

1. Scan for duplicates and group them by similarity patterns
2. Present each group with sample content
3. Offer options to:
   - Remove all duplicates in the group (y)
   - Skip the group (n)
   - Selectively process each duplicate individually (s)
4. Prompt for replacement text when removing duplicates (unless `--no-prompt` is specified)

### Examples

Process a single file interactively:
```bash
python dedup.py path/to/file.md
```

Process all files in a folder automatically (with same-sender duplicates):
```bash
python dedup.py --auto path/to/folder
```

Remove duplicates without any replacement text:
```bash
python dedup.py --no-prompt path/to/folder
```

Dry run to see what would be detected without making changes:
```bash
python dedup.py --dry-run --verbose path/to/folder
```

## What It Detects

The tool identifies several types of duplicates:

1. **Duplicate Messages** - Messages with the same content from:
   - The same sender (e.g., email replies, forwarded content)
   - Different senders (with higher similarity threshold)

2. **Repeating Paragraphs** - Content blocks that repeat within the document

3. **Common Email Patterns** - Recognizes patterns like:

   - "Name at HH:MM" format
   - "Name wrote:" format
   - Email headers (From, To, Subject, etc.)
   - Simple name headers followed by content

## Backups

Before modifying any file, the tool creates a backup in the `backups` directory, preserving the original file structure. If an error occurs during backup creation, a warning will be displayed.

## Formatting Fixes

When the `--no-format-fix` option is not specified, the tool also cleans up common formatting issues:
- Standardizes "Original Message" markers
- Fixes email header formatting
- Cleans excessive whitespace

## Troubleshooting

- **File Not Found Errors**: If files are removed during processing, the tool will now skip them and continue
- **Keyboard Interrupts**: Press Ctrl+C to gracefully exit the process
- **Empty Backup Folder**: Check for permission issues or path problems if backups aren't being created

## Notes

- The tool is designed for markdown files following the YYYY-MM-DD*.md naming pattern
- Files with embedded content (like `![[file.ext]]` syntax) are flagged during processing
- Large files may take longer to process due to the similarity comparison algorithms

## License

This tool is provided as-is under the MIT License.