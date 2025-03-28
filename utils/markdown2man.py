#!/usr/bin/env python3

###############################################################################
# Convert manual pages from markdown to MAN format
#
# Author(s): Anna Petrasova
#
# COPYRIGHT: (C) 2025 by the GRASS Development Team
#
#            This program is free software under the GNU General Public
#            License (>=v2). Read the file COPYING that comes with GRASS
#            for details.
#
###############################################################################

import argparse
import re
from pathlib import Path


def strip_yaml_from_markdown(content):
    # Remove YAML front matter
    return re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)

def parse_markdown(content):
    """Parse markdown into structured blocks"""
    lines = content.splitlines()
    processing_block = []
    processed_content = []

    buffer = ""
    state = "default"
    in_table = False

    for line in lines:
        stripped = line.strip()

        # Table detection
        if re.match(r'^\|.+\|$', stripped) and not in_table:
            if processing_block:
                processed_content.append({"markdown": "\n".join(processing_block), "type": state})
                processing_block = []
            state = "table"
            in_table = True
            processing_block.append(line)
            continue

        if in_table:
            if re.match(r'^\|.+\|$', stripped) or re.match(r'^\|-+', stripped):
                processing_block.append(line)
            else:
                processed_content.append({"markdown": "\n".join(processing_block), "type": state})
                processing_block = []
                state = "default"
                in_table = False
                buffer = line
            continue

        # Code block handling
        if line.strip().startswith("```"):
            if state == "code":
                processing_block.append(line)
                processed_content.append(
                    {"markdown": "\n".join(processing_block), "type": state}
                )
                processing_block = []
                state = "default"
            else:
                processed_content.append(
                    {"markdown": "\n".join(processing_block), "type": state}
                )
                processing_block = []
                processing_block.append(line)
                state = "code"
            continue

        # List handling
        if re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", line.strip()):
            if buffer:
                processing_block.append(buffer)
                buffer = ""
            if state != "list":
                processed_content.append(
                    {"markdown": "\n".join(processing_block), "type": state}
                )
                processing_block = []
                state = "list"

        # Empty line handling
        if line == "":
            if buffer:
                processing_block.append(buffer)
                buffer = ""
            if state != "default":
                processed_content.append(
                    {"markdown": "\n".join(processing_block), "type": state}
                )
                processing_block = []
                state = "default"
            processing_block.append(line)
            continue

        if buffer:
            buffer += " " + line
        else:
            buffer = line

        if line.endswith("  "):
            processing_block.append(buffer)
            buffer = ""

    if buffer:
        processing_block.append(buffer)
    if processing_block:
        processed_content.append(
            {"markdown": "\n".join(processing_block), "type": state}
        )

    merged_content = []
    for item in processed_content:
        if not item["markdown"]:
            continue
        if merged_content and merged_content[-1]["type"] == item["type"]:
            merged_content[-1]["markdown"] += "\n" + item["markdown"]
        else:
            merged_content.append(item)

    return merged_content

def process_headings(markdown):
    """Convert headings with hierarchical numbering and labels"""
    section_counter = [0]
    subsection_counter = [0]

    def convert_main_section(match):
        section_counter[0] += 1
        subsection_counter[0] = 0
        return f"\n.SH {section_counter[0]}. {match.group(1).upper()} (Main Section)\n"

    def convert_subsection(match):
        subsection_counter[0] += 1
        return (f"\n.SS {section_counter[0]}.{subsection_counter[0]} "
                f"{match.group(1).upper()} (Subsection)\n")

    markdown = re.sub(r"^## (.*)", convert_main_section, markdown, flags=re.MULTILINE)
    return re.sub(r"^### (.*)", convert_subsection, markdown, flags=re.MULTILINE)

def process_lists(markdown):
    markdown = process_special_characters(markdown)
    markdown = process_formatting(markdown)
    markdown = process_links(markdown)

    output = []
    current_level = 0
    list_stack = []
    bullet_styles = [r"\\(bu", r"\\(sq", r"\\(ci"] 

    for line in markdown.splitlines():
        match = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", line)
        if not match:
            continue

        indent, bullet, content = match.groups()
        new_level = len(indent) // 4

        # Handle list transitions
        while current_level > new_level:
            if list_stack:  # Add safety check
                output.append(f".RE\n\\fBEnd of Nested List (Level {current_level})\\fR\n")
                current_level -= 1
                list_stack.pop()

        if new_level > current_level or not list_stack:
            # Initialize stack if empty
            list_type = 'ordered' if bullet[:-1].isdigit() else 'unordered'
            output.append(
                f"\\fBStart of Nested List (Level {new_level}) "
                f"[{list_type.upper()}]\\fR\n"
                f".RS {4*(new_level+1)}n"
            )
            current_level = new_level
            list_stack.append({'type': list_type, 'counter': 1})

        # Add check for empty stack before access
        if not list_stack:
            continue

        # Format list items
        if list_stack[-1]['type'] == 'ordered':
            output.append(f'.IP "{list_stack[-1]["counter"]}." {4*(current_level+1)}n')
            list_stack[-1]["counter"] += 1
        else:
            bullet = bullet_styles[current_level % len(bullet_styles)]
            output.append(f'.IP "{bullet}" {4*(current_level+1)}n')
        
        output.append(f"{content}\n")

    # Close remaining lists
    while current_level > 0 and list_stack:
        output.append(f".RE\n\\fBEnd of Nested List (Level {current_level})\\fR\n")
        current_level -= 1
        list_stack.pop()

    return "".join(output)

def process_tables(markdown):
    processed = process_formatting(markdown)
    lines = processed.split('\n')
    
    if not lines or len(lines[0].strip()) == 0:
        return ""

    table = [
        "\\fBStart of Table\\fR",
        ".TS",
        "allbox tab(|);",
        "l " * len(lines[0].split("|")) + "."
    ]

    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip('|').split('|')]
        if i == 0:
            table.append("_")
        table.append("|" + "|".join(cells) + "|")

    table.append(".TE\n\\fBEnd of Table\\fR")
    return '\n'.join(table)

def process_parameters(markdown):
    """Handle parameter definitions with bold formatting"""
    return re.sub(
        r"^\*\*([a-z0-9_]*)\*\*=\*([a-z]*)\*( \*\*\[required\]\*\*)?",
        r'.IP "\\fB\1\\fR=*\2*\3" 4m',
        markdown,
        flags=re.MULTILINE,
    )

def process_flags(markdown):
    """Handle command-line flags with consistent formatting"""
    return re.sub(
        r"^\*\*-(.*?)\*\*", 
        r'.IP "\\fB-\1\\fR" 4m', 
        markdown, 
        flags=re.MULTILINE
    )

def process_code(markdown):
    """Preserve code blocks with monospace formatting"""
    in_code_block = False
    output = []
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            if in_code_block:
                output.append("\\fR\n.fi\n")
            else:
                output.append(".nf\n\\fC\n")
            in_code_block = not in_code_block
        else:
            output.append(re.sub(r"\\fC", r"\\fC ", line))
    return "\n".join(output)

def process_formatting(markdown):
    markdown = re.sub(r"\*\*\s*(\S(.*?\S)?)\s*\*\*", r"\\fB \1 \\fR", markdown, flags=re.DOTALL)
    markdown = re.sub(r"\*\s*(\S(.*?\S)?)\s*\*", r"\\fI \1 \\fR", markdown, flags=re.DOTALL)
    markdown = re.sub(r"\*\*\*\s*(\S(.*?\S)?)\s*\*\*\*", r"\\fB\\fI \1 \\fR\\fR", markdown, flags=re.DOTALL)
    
    return markdown

def process_links(markdown):
    """Replace Markdown links with display text"""
    markdown = re.sub(r"!\[.*?\]\(.*?\)", "", markdown)
    return re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", markdown)
bullet_styles = [r"\\(bu", r"\\(sq", r"\\(ci"]  # Use raw strings with double escapes

def process_special_characters(markdown):
    """Handle special characters"""
    markdown = markdown.replace(r"\[", "[")
    markdown = markdown.replace(r"\]", "]")
    markdown = markdown.replace(r"\#", "#")
    markdown = re.sub(r"(?<=\S) {2,}(?=\S)", " ", markdown)
    return re.sub(r"\\", r"\(rs", markdown)

def convert_markdown_to_man(input_file, output_file):
    markdown = Path(input_file).read_text()
    markdown = strip_yaml_from_markdown(markdown)
    blocks = parse_markdown(markdown)
    
    man_page = [
        '.TH I.ATCORR 1 "GRASS GIS Manual"',
        '.SH NAME\ni.atcorr \\- Atmospheric correction using 6S algorithm'
    ]

    for block in blocks:
        content_type = block["type"]
        content = block["markdown"]

        if content_type == "code":
            man_page.append(process_code(content))
        elif content_type == "list":
            man_page.append(process_lists(content))
        elif content_type == "table":
            man_page.append(process_tables(content))
        else:
            processed = process_default(content)
            man_page.append(processed)

    Path(output_file).write_text("\n".join(man_page))

def process_default(markdown):
    """Default processing pipeline"""
    transformations = [
        process_parameters,
        process_flags,
        lambda x: x.replace("&nbsp;&nbsp;&nbsp;&nbsp;", ""),
        process_special_characters,
        process_formatting,
        process_links,
        process_headings
    ]
    for transform in transformations:
        markdown = transform(markdown)
    return markdown


def main():
    parser = argparse.ArgumentParser(
        description="Convert enhanced Markdown to man page format"
    )
    parser.add_argument("input_file", help="Input Markdown file")
    parser.add_argument("output_file", help="Output man page file")
    args = parser.parse_args()
    
    convert_markdown_to_man(args.input_file, args.output_file)

if __name__ == "__main__":
    main()
