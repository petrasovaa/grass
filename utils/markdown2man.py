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

def strip_yaml_from_markdown(content):
    if content.startswith('---'):
        parts = content.split('---', 2)
        return parts[2].strip() if len(parts) == 3 else content
    return content

def replace_markdown_formatting(text):
    text = re.sub(r'\*\*(.*?)\*\*', r'\\fB\1\\fR', text)
    text = re.sub(r'__(.*?)__', r'\\fB\1\\fR', text)
    text = re.sub(r'\*(?!\*)(.*?)\*', r'\\fI\1\\fR', text)
    text = re.sub(r'_(?!_)(.*?)_', r'\\fI\1\\fR', text)
    return text

def remove_links(text):
    text = re.sub(r'!\[(.*?)\]\(.*?\)', r'\1', text)
    return re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)

def process_tables(markdown):
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    if len(lines) < 2 or not all('|' in line for line in lines[:2]):
        return markdown

    headers = [cell.strip() for cell in lines[0].strip('|').split('|')]
    rows = []
    for line in lines[2:]:
        if '|' not in line:
            continue
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        if len(cells) == len(headers):
            rows.append(cells)

    clean = lambda s: re.sub(r'[\u250C-\u257F]', '', s).strip()
    output = ['.TS', 'allbox;', 'c' * len(headers) + '.']
    output.append('\t'.join([replace_markdown_formatting(clean(h)) for h in headers]))

    for row in rows:
        output.append('\t'.join([replace_markdown_formatting(clean(cell)) for cell in row]))
        output.append('.sp 1')

    output.append('.TE')
    return '\n'.join(output)

def process_code(markdown):
    code_lines = []
    in_code = False
    for line in markdown.split('\n'):
        if line.strip().startswith('```'):
            in_code = not in_code
            if in_code:
                code_lines.append('.nf\n\\fC')
            else:
                code_lines.append('\\fR\n.fi')
        else:
            code_lines.append(line.replace('\\', '\\\\'))
    return '\n'.join(code_lines)

def process_lists(markdown):
    output = []
    indent_stack = [0]

    for line in markdown.splitlines():
        match = re.match(r'^(\s*)([-*\u2022]|\d+\.)\s+(.*)', line)
        if not match:
            continue

        indent = len(match.group(1))
        bullet = match.group(2)
        text = replace_markdown_formatting(remove_links(match.group(3)))

        while indent_stack[-1] > indent:
            output.append(".RE")
            indent_stack.pop()

        if indent > indent_stack[-1]:
            output.append(".RS 4")
            indent_stack.append(indent)

        output.append(f'.IP "{bullet}" 4\n{text}')

    while len(indent_stack) > 1:
        output.append(".RE")
        indent_stack.pop()

    return '\n'.join(output)

def process_headings(markdown):
    def heading_replacer(match):
        level = len(match.group(1))
        text = replace_markdown_formatting(remove_links(match.group(2).strip()))
        return f'.{"SH" if level == 1 else "SS"} "{text}"'

    return re.sub(r'^(#{1,3}) (.*)$', heading_replacer, markdown, flags=re.MULTILINE)

def process_paragraphs(text):
    text = remove_links(text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = replace_markdown_formatting(text)
    return text

def format_authors_block(lines):
    result = ['.SH AUTHORS']
    for i in range(0, len(lines), 2):
        if i + 1 < len(lines):
            title = lines[i].strip('* ').strip(':')
            author = lines[i+1].strip()
            result.append('.PP')
            result.append(f'\\fI{title}:\\fR')
            result.append('.br')
            result.append(remove_links(author))
    return '\n'.join(result)

def parse_markdown(content):
    blocks = []
    current_block = {"type": "text", "content": []}
    in_code = False
    in_list = False
    in_table = False
    in_authors = False

    for line in content.split('\n'):
        stripped = line.strip()

        if stripped.startswith('```'):
            if current_block["content"]:
                blocks.append(current_block)
            in_code = not in_code
            current_block = {"type": "code", "content": [line]}
            continue

        if in_code:
            current_block["content"].append(line)
            continue

        if '## AUTHORS' in line:
            in_authors = True
            if current_block["content"]:
                blocks.append(current_block)
            current_block = {"type": "authors", "content": []}
            continue

        if in_authors:
            if stripped.startswith('##') and '## AUTHORS' not in stripped:
                in_authors = False
                blocks.append(current_block)
                current_block = {"type": "text", "content": [line]}
            else:
                current_block["content"].append(line)
            continue

        if '|' in line and (not in_table or stripped.startswith('|')):
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

        list_match = re.match(r'^(\s*)([-*\u2022]|\d+\.)\s+', line)
        if list_match:
            if not in_list and current_block["content"]:
                blocks.append(current_block)
                current_block = {"type": "list", "content": []}
            in_list = True
            current_block["content"].append(line)
            continue
        elif in_list:
            if stripped == '':
                blocks.append(current_block)
                current_block = {"type": "text", "content": []}
                in_list = False
            else:
                current_block["content"].append(line)
            continue

        heading_match = re.match(r'^(#{1,3}) (.*)', line)
        if heading_match:
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

def convert_markdown_to_man(input_file, output_file):
    content = Path(input_file).read_text(encoding='utf-8')
    content = strip_yaml_from_markdown(content)
    blocks = parse_markdown(content)

    man_page = [
        '.TH "i.atcorr" "1" "" "GRASS 7.9.dev" "GRASS GIS User\'s Manual"',
        '.ad l',
        '.SH NAME',
        '\\fI\\fBi.atcorr\\fR\\fR  - Performs atmospheric correction using the 6S algorithm.',
        '.br',
        '6S - Second Simulation of Satellite Signal in the Solar Spectrum.',
        '.SH KEYWORDS',
        'imagery, atmospheric correction, radiometric conversion, radiance, reflectance, satellite'
    ]

    for block in blocks:
        content_text = '\n'.join(block["content"])
        if block["type"] == "code":
            man_page.append(process_code(content_text))
        elif block["type"] == "list":
            man_page.append(process_lists(content_text))
        elif block["type"] == "table":
            man_page.append(process_tables(content_text))
        elif block["type"] == "heading":
            man_page.append(process_headings(content_text))
        elif block["type"] == "authors":
            man_page.append(format_authors_block(block["content"]))
        else:
            processed_text = process_paragraphs(content_text)
            if processed_text:
                man_page.append(f'.PP\n{processed_text}')

    Path(output_file).write_text('\n'.join(man_page), encoding='utf-8')

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert Markdown to man page")
    parser.add_argument('input', help="Input Markdown file")
    parser.add_argument('output', help="Output man page file")
    args = parser.parse_args()
    convert_markdown_to_man(args.input, args.output)
