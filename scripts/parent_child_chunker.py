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
import xml.etree.ElementTree as ET
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

def parse_4fd_to_parents(file_content: str, filename: str) -> List[Dict[str, Any]]:
    """
    Parses a .4fd XML file content into logical parent chunks based on XML elements:
    - Layout
    - FormItems
    - BindFiles
    - ScreenRecords
    """
    try:
        root = ET.fromstring(file_content)
    except Exception as e:
        raise ValueError(f"XML parsing failed for {filename}: {str(e)}")
        
    parents = []
    target_tags = {'Layout', 'FormItems', 'BindFiles', 'ScreenRecords'}
    tag_map = {t.lower(): t for t in target_tags}
    
    for elem in root.iter():
        tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        tag_lower = tag_local.lower()
        if tag_lower in tag_map:
            standard_tag = tag_map[tag_lower]
            try:
                xml_str = ET.tostring(elem, encoding='utf-8').decode('utf-8')
            except Exception as e:
                xml_str = f"<!-- Error serializing node: {str(e)} -->"
                
            parents.append({
                "parent_id": f"{filename}_{standard_tag}",
                "type": standard_tag,
                "name": standard_tag,
                "content": xml_str
            })
            
    if not parents:
        # Fallback: treat the root element as the parent chunk
        tag_local = root.tag.split('}')[-1] if '}' in root.tag else root.tag
        try:
            xml_str = ET.tostring(root, encoding='utf-8').decode('utf-8')
        except Exception as e:
            xml_str = f"<!-- Error serializing node: {str(e)} -->"
            
        parents.append({
            "parent_id": f"{filename}_{tag_local}",
            "type": tag_local,
            "name": tag_local,
            "content": xml_str
        })
            
    return parents

def extract_4fd_metadata(elem: ET.Element, parent_id: str, source_file: str, node_type: str) -> Dict[str, Any]:
    """
    Extracts all attributes from an XML element and puts them in metadata,
    ensuring 'id' or other identifiers are promoted.
    """
    metadata = {
        "parent_id": parent_id,
        "source_file": source_file,
        "node_type": node_type
    }
    
    # Store all element attributes (cleaning namespace prefix from attribute names)
    for attr_name, attr_val in elem.attrib.items():
        clean_attr_name = attr_name.split('}')[-1] if '}' in attr_name else attr_name
        metadata[clean_attr_name] = attr_val
        
    # Standardize identifier (id, name, field, text, etc. in lowercase)
    for k in ["name", "id", "field", "text"]:
        val = elem.get(k) or elem.get(k.upper())
        if val:
            metadata[k] = val
            
    return metadata

def slice_4fd_to_children(
    parent_chunk: Dict[str, Any],
    source_file: str
) -> List[Dict[str, Any]]:
    """
    Slices a .4fd Parent Chunk content into child XML fragments with rich metadata.
    - If parent type is FormItems, slice by FormItem elements.
    - If parent type is Layout, slice by Grid or Table elements.
    - For other parent types, slice by direct child elements.
    """
    parent_id = parent_chunk["parent_id"]
    parent_type = parent_chunk["type"]
    content = parent_chunk["content"]
    
    try:
        root = ET.fromstring(content)
    except Exception:
        return []
        
    children = []
    
    if parent_type == "FormItems":
        # Traverse for all FormItem nodes
        for elem in root.iter():
            tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_local.lower() == "formitem":
                try:
                    child_xml = ET.tostring(elem, encoding='utf-8').decode('utf-8')
                except Exception:
                    continue
                metadata = extract_4fd_metadata(elem, parent_id, source_file, tag_local)
                children.append({
                    "child_content": child_xml,
                    "metadata": metadata
                })
                
    elif parent_type == "Layout":
        # Traverse for all Grid and Table nodes
        for elem in root.iter():
            tag_local = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_local.lower() in ["grid", "table"]:
                try:
                    child_xml = ET.tostring(elem, encoding='utf-8').decode('utf-8')
                except Exception:
                    continue
                metadata = extract_4fd_metadata(elem, parent_id, source_file, tag_local)
                children.append({
                    "child_content": child_xml,
                    "metadata": metadata
                })
                
    else:
        # For BindFiles and ScreenRecords, slice by their direct children
        for child_elem in list(root):
            tag_local = child_elem.tag.split('}')[-1] if '}' in child_elem.tag else child_elem.tag
            try:
                child_xml = ET.tostring(child_elem, encoding='utf-8').decode('utf-8')
            except Exception:
                continue
            metadata = extract_4fd_metadata(child_elem, parent_id, source_file, tag_local)
            children.append({
                "child_content": child_xml,
                "metadata": metadata
            })
            
    return children

def process_file(
    file_path: str, 
    child_size: int = 250, 
    child_overlap: int = 50
) -> List[Dict[str, Any]]:
    """
    Reads a file (.4gl or .4fd), generates Parent Chunks, slices them into Child Chunks, 
    and returns a combined list of all child chunks with metadata.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    filename = os.path.basename(file_path)
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        file_content = f.read()
        
    is_4fd = filename.lower().endswith('.4fd')
    
    if is_4fd:
        parents = parse_4fd_to_parents(file_content, filename)
        all_children = []
        for parent in parents:
            children = slice_4fd_to_children(
                parent_chunk=parent,
                source_file=filename
            )
            all_children.extend(children)
    else:
        parents = parse_4gl_to_parents(file_content, filename)
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
    parser = argparse.ArgumentParser(description="Parent-Child Chunking Script for Genero 4GL/4FD")
    parser.add_argument("file_path", help="Path to the .4gl or .4fd file to parse")
    parser.add_argument("--size", type=int, default=250, help="Child chunk size in characters (default: 250)")
    parser.add_argument("--overlap", type=int, default=50, help="Child chunk overlap in characters (default: 50)")
    parser.add_argument("--output", help="Optional JSON output file path to write results")
    
    args = parser.parse_args()
    
    try:
        results = process_file(args.file_path, args.size, args.overlap)
        
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
