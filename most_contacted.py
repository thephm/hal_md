import os
import re
import yaml
import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime

# Directory containing markdown files
DIRECTORY = '/mnt/c/data/notes/People'

# Fields to be processed
FIELDS_TO_PROCESS = ['to', 'from', 'people']

def parse_arguments():
    parser = argparse.ArgumentParser(description='Process markdown files to find most contacted people.')
    parser.add_argument('-m', '--my-slug', type=str, required=True, help='Your slug to exclude from the count')
    parser.add_argument('-n', '--top-n', type=int, default=None, help='Number of top names to display')
    parser.add_argument('-o', '--output-csv', type=str, help='Output CSV file to save the results')
    return parser.parse_args()

def extract_frontmatter(content):
    yaml_pattern = re.compile(r'^---\n(.*?)\n---', re.DOTALL)
    yaml_match = yaml_pattern.search(content)
    if yaml_match:
        try:
            return yaml.safe_load(yaml_match.group(1))
        except yaml.YAMLError as e:
            print(f"Error parsing YAML: {e}")
    return None

def process_file(file_path, my_slug, fields_to_process, name_counter, person_dates):
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
        content = file.read()
        frontmatter = extract_frontmatter(content)
        if frontmatter:
            for field in fields_to_process:
                if field in frontmatter:
                    if isinstance(frontmatter[field], list):
                        for name in frontmatter[field]:
                            if name != my_slug:
                                name_counter.update([name])
                                person_dates[name].append(os.path.basename(file_path)[:10])
                    else:
                        if frontmatter[field] != my_slug:
                            name_counter.update([frontmatter[field]])
                            person_dates[frontmatter[field]].append(os.path.basename(file_path)[:10])

def process_files(directory, my_slug, fields_to_process):
    name_counter = Counter()
    person_dates = defaultdict(list)
    filename_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}\.md$')

    for root, _, files in os.walk(directory):
        for filename in files:
            if filename_pattern.match(filename):
                file_path = os.path.join(root, filename)
                process_file(file_path, my_slug, fields_to_process, name_counter, person_dates)
    return name_counter, person_dates

def print_top_names(top_names, person_dates, output_csv=None):
    rows = []
    for name, count in top_names:
        dates = [datetime.strptime(date, '%Y-%m-%d') for date in person_dates[name]]
        if dates:
            min_date = min(dates)
            max_date = max(dates)
            date_diff = max_date - min_date
            years, remainder = divmod(date_diff.days, 365)
            months, days = divmod(remainder, 30)
            first_date = min_date.strftime('%Y-%m-%d')
            last_date = max_date.strftime('%Y-%m-%d')
        else:
            years = months = days = 0
            first_date = 'N/A'
            last_date = 'N/A'

        count_label = "day" if count == 1 else "days"
        row = [name, count, years, months, days, first_date, last_date]
        rows.append(row)

        if not output_csv:
            duration = f"{years}, {months}, {days}"
            print(f"{name}: {count} {count_label} across {duration} since {first_date}. Most recently on {last_date}")

    if output_csv:
        with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
            csvwriter = csv.writer(csvfile)
            csvwriter.writerow(['Name', 'Count', 'Years', 'Months', 'Days', 'First Date', 'Last Date'])
            csvwriter.writerows(rows)

def main():
    args = parse_arguments()
    name_counter, person_dates = process_files(DIRECTORY, args.my_slug, FIELDS_TO_PROCESS)
    
    if args.top_n:
        top_names = name_counter.most_common(args.top_n)
    else:
        top_names = name_counter.most_common()

    print_top_names(top_names, person_dates, args.output_csv)

if __name__ == "__main__":
    main()