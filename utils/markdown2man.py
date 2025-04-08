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

import re
import argparse
from pathlib import Path

def strip_yaml_from_markdown(markdown):
    if markdown.startswith('---'):
        parts = markdown.split('---', 2)
        return parts[2].strip() if len(parts) == 3 else markdown
    return markdown

def replace_markdown_formatting(text):
    text = re.sub(r'\*\*(.*?)\*\*', r'\\fB\1\\fR', text)
    text = re.sub(r'__(.*?)__', r'\\fB\1\\fR', text)
    text = re.sub(r'\*(?!\*)(.*?)\*', r'\\fI\1\\fR', text)
    text = re.sub(r'_(?!_)(.*?)_', r'\\fI\1\\fR', text)
    return text

def process_tables(markdown):
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    if len(lines) < 2 or not all('|' in line for line in lines[:2]):
        return markdown

    # Clean up table headers and separators
    headers = lines[0].strip('|').split('|')
    separator = lines[1].strip('|').split('|')
    rows = [line.strip('|').split('|') for line in lines[2:] if '|' in line]

    # Remove box-drawing characters
    clean = lambda s: re.sub(r'[┌┐├┤┬┴─]', '', s).strip()
    
    output = [".TS", "allbox;", "c" * len(headers) + "."]
    processed_headers = [replace_markdown_formatting(clean(h)) for h in headers]
    output.append("\t".join(processed_headers))

    for row in rows:
        processed_cells = [replace_markdown_formatting(clean(cell)) for cell in row]
        output.append("\t".join(processed_cells))

    output.append(".TE")
    return "\n".join(output)

def parse_markdown(markdown):
    blocks = []
    current_block = {"type": "text", "content": []}
    in_code = False
    in_list = False
    in_table = False

    for line in markdown.splitlines():
        line = line.rstrip()
        
        # Detect code blocks
        if line.strip().startswith('```'):
            if current_block["content"]:
                blocks.append(current_block)
            in_code = not in_code
            current_block = {"type": "code", "content": [line]}
            continue
        
        if in_code:
            current_block["content"].append(line)
            continue

        # Detect tables
        if '|' in line and (not in_table or line.strip().startswith('|')):
            if not in_table and current_block["content"]:
                blocks.append(current_block)
                current_block = {"type": "table", "content": []}
            in_table = True
            current_block["content"].append(line)
            continue
        elif in_table:
            blocks.append(current_block)
            current_block = {"type": "text", "content": []}
            in_table = False

        # Detect lists
        list_match = re.match(r'^(\s*)([-*•]|\d+\.)\s+', line)
        if list_match:
            if not in_list and current_block["content"]:
                blocks.append(current_block)
                current_block = {"type": "list", "content": []}
            in_list = True
            current_block["content"].append(line)
            continue
        elif in_list:
            if line.strip() == '':
                blocks.append(current_block)
                current_block = {"type": "text", "content": []}
                in_list = False
            else:
                current_block["content"].append(line)
            continue

        # Detect headings
        if re.match(r'^#{1,3} ', line):
            if current_block["content"]:
                blocks.append(current_block)
            current_block = {"type": "heading", "content": [line]}
            blocks.append(current_block)
            current_block = {"type": "text", "content": []}
            continue

        current_block["content"].append(line)

    if current_block["content"]:
        blocks.append(current_block)
    
    return blocks

def process_headings(markdown):
    def heading_replacer(match):
        level = len(match.group(1))
        text = replace_markdown_formatting(match.group(2).strip())
        return f'.{"SH" if level == 1 else "SS"} "{text}"'
    
    return re.sub(
        r'^(#{1,3}) (.*)$',
        heading_replacer,
        markdown,
        flags=re.MULTILINE
    )

def process_code(markdown):
    code_lines = [line for line in markdown.splitlines() if not line.strip().startswith('```')]
    return ".nf\n\\fC\n" + "\n".join(code_lines) + "\n\\fR\n.fi"

def process_lists(markdown):
    output = []
    indent_stack = [0]
    
    for line in markdown.splitlines():
        match = re.match(r'^(\s*)([-*•]|\d+\.)\s+(.*)', line)
        if not match:
            continue
            
        indent = len(match.group(1))
        bullet = match.group(2)
        text = replace_markdown_formatting(match.group(3))

        while indent_stack[-1] > indent:
            output.append(".RE")
            indent_stack.pop()

        if indent > indent_stack[-1]:
            output.append(".RS 4")
            indent_stack.append(indent)

        if bullet.isdigit():
            output.append(f'.IP "{bullet}." 4\n{text}')
        else:
            output.append(f'.IP "\\(bu" 4\n{text}')

    while len(indent_stack) > 1:
        output.append(".RE")
        indent_stack.pop()

    return "\n".join(output)

def process_paragraphs(text):
    text = re.sub(r'\s+', ' ', text).strip()
    text = process_special_characters(text)
    text = replace_markdown_formatting(text)
    return text

def process_special_characters(text):
    replacements = {
        '[': r'\[',
        ']': r'\]',
        '\\': r'\(rs',
        '~': r'\(ti',
        '^': r'\(ha',
        '`': r'\(ga'
    }
    for char, escape in replacements.items():
        text = text.replace(char, escape)
    return text

def convert_markdown_to_man(input_file, output_file):
    content = Path(input_file).read_text(encoding='utf-8')
    content = strip_yaml_from_markdown(content)
    blocks = parse_markdown(content)

    man_page = ['.TH "MANPAGE" "1" "" "" ""']
    
    for block in blocks:
        if block["type"] == "code":
            man_page.append(process_code('\n'.join(block["content"])))
        elif block["type"] == "list":
            man_page.append(process_lists('\n'.join(block["content"])))
        elif block["type"] == "table":
            man_page.append(process_tables('\n'.join(block["content"])))
        elif block["type"] == "heading":
            man_page.append(process_headings('\n'.join(block["content"])))
        else:
            processed_text = process_paragraphs('\n'.join(block["content"]))
            if processed_text:
                man_page.append(f'.PP\n{processed_text}')

    Path(output_file).write_text('\n'.join(man_page), encoding='utf-8')
    print(f"Man page generated: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert Markdown to man page")
    parser.add_argument('input', help="Input Markdown file")
    parser.add_argument('output', help="Output man page file")
    args = parser.parse_args()
    convert_markdown_to_man(args.input, args.output)
