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
    """Remove YAML front matter from markdown content."""
    return re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)

def get_first_sentence(text):
    """Extract first meaningful paragraph for NAME section."""
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    for para in paragraphs:
        if not para.startswith('#') and len(para.split()) > 3:
            clean = re.sub(r'[\*_`]', '', para.split('\n')[0])
            return clean[:80]
    return "Manages module functionality"

def convert_table(md_table):
    """Convert markdown tables to man page format with proper alignment."""
    lines = [line.strip() for line in md_table.split('\n') 
             if line.strip() and '|' in line]
    lines = [line for line in lines if not re.match(r'^[\|\-\s]+$', line)]
    
    # Calculate column widths
    col_widths = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        for i, cell in enumerate(cells):
            if i >= len(col_widths):
                col_widths.append(0)
            col_widths[i] = max(col_widths[i], len(cell))
    
    # Format with consistent spacing
    output = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        padded = [f" {cell.ljust(col_widths[i])} " for i, cell in enumerate(cells)]
        output.append(''.join(padded))
    return '\n'.join(output) + '\n'

def parse_markdown(content):
    """Parse markdown content into typed blocks (code, lists, default)."""
    # Handle tables first
    content = re.sub(
        r'(\|.+\|(\n\|.+\|)+)',
        lambda m: f"TABLE_BLOCK:{m.group(0)}:END_TABLE",
        content
    )

    lines = content.splitlines()
    processing_block = []
    processed_content = []
    buffer = ""
    state = "default"

    for line in lines:
        if line.strip().startswith("```"):
            if state == "code":
                processing_block.append(line)
                processed_content.append({"markdown": "\n".join(processing_block), "type": state})
                processing_block = []
                state = "default"
            else:
                if buffer:
                    processing_block.append(buffer)
                    buffer = ""
                processed_content.append({"markdown": "\n".join(processing_block), "type": state})
                processing_block = [line]
                state = "code"
            continue

        if state == "code":
            processing_block.append(line)
            continue

        if re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", line.strip()):
            if buffer:
                processing_block.append(buffer)
                buffer = ""
            if state != "list":
                processed_content.append({"markdown": "\n".join(processing_block), "type": state})
                processing_block = []
                state = "list"

        if line == "":
            if buffer:
                processing_block.append(buffer)
                buffer = ""
            if state != "default":
                processed_content.append({"markdown": "\n".join(processing_block), "type": state})
                processing_block = []
                state = "default"
            processing_block.append(line)
            continue

        if buffer:
            buffer += " " + line
        else:
            buffer += line

        if line.endswith("  "):
            processing_block.append(buffer)
            buffer = ""

    if buffer:
        processing_block.append(buffer)
    if processing_block:
        processed_content.append({"markdown": "\n".join(processing_block), "type": state})

    # Merge adjacent blocks of same type
    merged = []
    for item in processed_content:
        if not item["markdown"]:
            continue
        if merged and merged[-1]["type"] == item["type"]:
            merged[-1]["markdown"] += "\n" + item["markdown"]
        else:
            merged.append(item)
    return merged

def process_parameters(markdown):
    """Handle GRASS parameters and flags with proper .IP formatting."""
    # Process flags (-p) and parameters (region)
    markdown = re.sub(
        r'([^\w\n])(\*\*|\*|_)([a-z0-9_\-]+)(\*\*|\*|_)([^\w]|$)',
        r'\1\n.IP "\2\3\4" 4\n\5',
        markdown
    )
    # Clean up formatting
    markdown = re.sub(r'\.IP\n\.IP', '.IP', markdown)
    return re.sub(r'(\n\.IP "[^"]+" 4\n)\s+', r'\1', markdown)

def process_formatting(markdown):
    """Apply man page formatting for bold/italic text."""
    markdown = re.sub(r"\*\*\*(.+?)\*\*\*", r"\\fB\\fI\1\\fR", markdown)
    markdown = re.sub(r"\*\*(.+?)\*\*", r"\\fB\1\\fR", markdown)
    return re.sub(r"\*(.+?)\*", r"\\fI\1\\fR", markdown)

def process_headings(markdown):
    """Convert markdown headings to man page sections."""
    markdown = re.sub(r"^#{1,2} (.*)", r".SH \1".upper(), markdown, flags=re.MULTILINE)
    return re.sub(r"^#{3,} (.*)", r".SS \1", markdown, flags=re.MULTILINE)

def process_code(markdown):
    """Format code blocks with proper man page syntax."""
    in_code_block = False
    output = []
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            if in_code_block:
                output.append("\\fR\n.fi")
            else:
                lang = line.strip('`').strip()
                output.append(f".nf\n\\fC\n{lang + ': ' if lang else ''}")
            in_code_block = not in_code_block
        else:
            output.append(re.sub(r"\\", r"\\\\", line) if in_code_block else line)
    return "\n".join(output)

def process_lists(markdown):
    """Convert markdown lists to man page format."""
    output = []
    indent_levels = []
    for line in markdown.splitlines():
        match = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)", line)
        if not match:
            continue
        spaces, bullet, text = match.groups()
        level = len(spaces)
        
        while indent_levels and indent_levels[-1] > level:
            output.append(".RE")
            indent_levels.pop()
            
        if not indent_levels or indent_levels[-1] < level:
            output.append(".RS 4n")
            indent_levels.append(level)
            
        output.append(f'.IP "{bullet}" 4n\n{text}' if bullet.isdigit() 
                     else f'.IP \\(bu 4n\n{text}')
    
    while indent_levels:
        output.append(".RE")
        indent_levels.pop()
    return "\n".join(output)

def convert_markdown_to_man(input_file, output_file):
    """Main conversion function from markdown to man page format."""
    markdown = Path(input_file).read_text(encoding='utf-8')
    markdown = strip_yaml_from_markdown(markdown)
    
    title = Path(input_file).stem.upper()
    first_para = get_first_sentence(markdown.split('\n\n')[1]) if '\n\n' in markdown else ""
    
    blocks = parse_markdown(markdown)
    
    result = [
        f'.TH {title} 1 "GRASS GIS User\'s Manual"\n',
        f'.SH NAME\n\\fB{title}\\fR \\- {first_para}\n',
        f'.SH SYNOPSIS\n\\fB{title.lower()}\\fR\n.br\n'
    ]
    
    for block in blocks:
        if block["type"] == "code":
            result.append(process_code(block["markdown"]))
        elif block["type"] == "list":
            result.append(process_lists(block["markdown"]))
        else:
            content = block["markdown"]
            if "TABLE_BLOCK:" in content:
                result.append(convert_table(content[12:-10]))
            else:
                content = re.sub(r"([^\n\s])  $", r"\1\n.br", content, flags=re.MULTILINE)
                content = process_formatting(content)
                content = process_headings(content)
                content = process_parameters(content)
                result.append(content)
    
    Path(output_file).write_text("\n".join(result), encoding='utf-8')

def main():
    """Command line interface for the converter."""
    parser = argparse.ArgumentParser(
        description="Convert GRASS GIS markdown docs to man pages",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("input_file", help="Input markdown file path")
    parser.add_argument("output_file", help="Output man page file path")
    args = parser.parse_args()
    
    convert_markdown_to_man(args.input_file, args.output_file)
    print(f"Successfully converted {args.input_file} to {args.output_file}")

if __name__ == "__main__":
    main()
