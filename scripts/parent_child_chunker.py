#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Parent-Child Chunking Script for Genero 4GL Source Code.
This script slices a 4GL file into logical structure-based "Parent Chunks" 
(such as FUNCTIONS, REPORTS, MAIN, and GLOBAL declarations) and further
splits each Parent Chunk into overlapping "Child Chunks" for embedding models.
"""

import os
import re
import json
import argparse
from typing import List, Dict, Any

def parse_4gl_to_parents(file_content: str, filename: str) -> List[Dict[str, Any]]:
    """
    Slices a 4GL file content into logical parent chunks based on 4GL syntax structures:
    - MAIN ... END MAIN
    - FUNCTION <name> ... END FUNCTION
    - REPORT <name> ... END REPORT
    - GLOBALS/DATABASE/DEFINE outside blocks are collected into "Global_Declarations".
    """
    lines = file_content.splitlines()
    parents = []
    
    current_block_type = None  # 'MAIN', 'FUNCTION', 'REPORT'
    current_block_name = None
    current_block_lines = []
    
    global_lines = []
    inside_block_comment = False
    
    # Regex patterns for block boundary detection (case-insensitive)
    func_start_pat = re.compile(r'^\s*FUNCTION\s+(\w+)', re.IGNORECASE)
    report_start_pat = re.compile(r'^\s*REPORT\s+(\w+)', re.IGNORECASE)
    main_start_pat = re.compile(r'^\s*MAIN\b', re.IGNORECASE)
    
    func_end_pat = re.compile(r'^\s*END\s+FUNCTION\b', re.IGNORECASE)
    report_end_pat = re.compile(r'^\s*END\s+REPORT\b', re.IGNORECASE)
    main_end_pat = re.compile(r'^\s*END\s+MAIN\b', re.IGNORECASE)
    
    for line in lines:
        line_stripped = line.strip()
        
        # 1. Skip block-boundary checks for single-line comments but keep the line content
        if line_stripped.startswith('#') or line_stripped.startswith('--'):
            if current_block_type is None:
                global_lines.append(line)
            else:
                current_block_lines.append(line)
            continue
            
        # 2. Track block comments { ... }
        if '{' in line_stripped and '}' not in line_stripped:
            inside_block_comment = True
            if current_block_type is None:
                global_lines.append(line)
            else:
                current_block_lines.append(line)
            continue
        elif '}' in line_stripped and '{' not in line_stripped:
            inside_block_comment = False
            if current_block_type is None:
                global_lines.append(line)
            else:
                current_block_lines.append(line)
            continue
        elif inside_block_comment:
            if current_block_type is None:
                global_lines.append(line)
            else:
                current_block_lines.append(line)
            continue
            
        # 3. Main parser logic when outside any structure block
        if current_block_type is None:
            main_match = main_start_pat.match(line)
            func_match = func_start_pat.match(line)
            report_match = report_start_pat.match(line)
            
            if main_match:
                current_block_type = 'MAIN'
                current_block_name = 'MAIN'
                current_block_lines = [line]
            elif func_match:
                current_block_type = 'FUNCTION'
                current_block_name = func_match.group(1)
                current_block_lines = [line]
            elif report_match:
                current_block_type = 'REPORT'
                current_block_name = report_match.group(1)
                current_block_lines = [line]
            else:
                # Outside any block, append to global declaration lines
                global_lines.append(line)
        else:
            # Inside a block, append the line
            current_block_lines.append(line)
            
            # Check for block ending markers
            if current_block_type == 'MAIN' and main_end_pat.match(line):
                parents.append({
                    "parent_id": f"{filename}_MAIN",
                    "type": "MAIN",
                    "name": "MAIN",
                    "content": "\n".join(current_block_lines)
                })
                current_block_type = None
                current_block_name = None
                current_block_lines = []
            elif current_block_type == 'FUNCTION' and func_end_pat.match(line):
                parents.append({
                    "parent_id": f"{filename}_{current_block_name}",
                    "type": "FUNCTION",
                    "name": current_block_name,
                    "content": "\n".join(current_block_lines)
                })
                current_block_type = None
                current_block_name = None
                current_block_lines = []
            elif current_block_type == 'REPORT' and report_end_pat.match(line):
                parents.append({
                    "parent_id": f"{filename}_{current_block_name}",
                    "type": "REPORT",
                    "name": current_block_name,
                    "content": "\n".join(current_block_lines)
                })
                current_block_type = None
                current_block_name = None
                current_block_lines = []
                
    # Capture any unclosed blocks (graceful fallback)
    if current_block_type and current_block_lines:
        parents.append({
            "parent_id": f"{filename}_{current_block_name}",
            "type": current_block_type,
            "name": current_block_name,
            "content": "\n".join(current_block_lines)
        })
        
    # Append global declarations block if there is any content
    if global_lines:
        global_content = "\n".join(global_lines).strip()
        if global_content:
            parents.append({
                "parent_id": f"{filename}_Global_Declarations",
                "type": "GLOBAL",
                "name": "Global_Declarations",
                "content": global_content
            })
            
    return parents

def slice_to_children(
    content: str, 
    parent_chunk: Dict[str, Any], 
    source_file: str, 
    child_size: int = 250, 
    child_overlap: int = 50
) -> List[Dict[str, Any]]:
    """
    Slices parent block content into child chunks of fixed character length
    with an overlapping sliding window.
    """
    children = []
    content_len = len(content)
    step = child_size - child_overlap
    
    if step <= 0:
        step = child_size  # Avoid division/loop locks
        
    # If the parent block content is shorter than child_size, return it as a single chunk
    if content_len <= child_size:
        if content.strip():
            children.append({
                "child_content": content,
                "metadata": {
                    "parent_id": parent_chunk["parent_id"],
                    "source_file": source_file,
                    "type": parent_chunk["type"],
                    "function_name": parent_chunk["name"]
                }
            })
        return children
        
    start = 0
    while start < content_len:
        end = min(start + child_size, content_len)
        chunk_text = content[start:end]
        
        if chunk_text.strip():
            children.append({
                "child_content": chunk_text,
                "metadata": {
                    "parent_id": parent_chunk["parent_id"],
                    "source_file": source_file,
                    "type": parent_chunk["type"],
                    "function_name": parent_chunk["name"]
                }
            })
            
        if end >= content_len:
            break
        start += step
        
    return children

def process_4gl_file(
    file_path: str, 
    child_size: int = 250, 
    child_overlap: int = 50
) -> List[Dict[str, Any]]:
    """
    Reads a .4gl file, generates Parent Chunks, slices them into Child Chunks, 
    and returns a combined list of all child chunks with metadata.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    filename = os.path.basename(file_path)
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        file_content = f.read()
        
    # 1. Parse parent blocks
    parents = parse_4gl_to_parents(file_content, filename)
    
    # 2. Slice each parent block into child chunks
    all_children = []
    for parent in parents:
        children = slice_to_children(
            content=parent["content"],
            parent_chunk=parent,
            source_file=filename,
            child_size=child_size,
            child_overlap=child_overlap
        )
        all_children.extend(children)
        
    return all_children

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parent-Child Chunking Script for Genero 4GL")
    parser.add_argument("file_path", help="Path to the .4gl file to parse")
    parser.add_argument("--size", type=int, default=250, help="Child chunk size in characters (default: 250)")
    parser.add_argument("--overlap", type=int, default=50, help="Child chunk overlap in characters (default: 50)")
    parser.add_argument("--output", help="Optional JSON output file path to write results")
    
    args = parser.parse_args()
    
    try:
        results = process_4gl_file(args.file_path, args.size, args.overlap)
        
        # Write to JSON file if specified, else print summary
        if args.output:
            with open(args.output, "w", encoding="utf-8") as out_f:
                json.dump(results, out_f, ensure_ascii=False, indent=2)
            print(f"Successfully processed {args.file_path}. Sliced into {len(results)} child chunks. Output written to {args.output}")
        else:
            print(json.dumps(results[:5], ensure_ascii=False, indent=2))
            print(f"\n... Total of {len(results)} child chunks processed (printed first 5).")
            
    except Exception as e:
        print(f"Error processing file: {e}")
