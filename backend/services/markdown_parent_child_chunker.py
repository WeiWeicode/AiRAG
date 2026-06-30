#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Markdown Parent-Child Chunking Service.
Slices Markdown (.md) documents into logical header-based "Parent Chunks"
and further splits them into small overlapping "Child Chunks" with heading prefixes
for semantic vector retrieval.

Supports both LangChain-based splitting and a pure-Python fallback.
"""

import os
import re
import hashlib
from typing import List, Dict, Any

try:
    from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False


def generate_parent_id(filename: str, header_path: Dict[str, str]) -> str:
    """
    Generates a unique parent ID based on the filename and the header path.
    """
    header_keys = ["Header 1", "Header 2", "Header 3", "Header 4", "Header 5", "Header 6"]
    path_list = [header_path[k] for k in header_keys if k in header_path]
    path_str = " > ".join(path_list)
    unique_str = f"{filename}_{path_str}"
    # Use MD5 hash to create a unique suffix of fixed length
    hash_val = hashlib.md5(unique_str.encode("utf-8")).hexdigest()[:12]
    return f"{filename}_{hash_val}"


def pure_python_markdown_split(markdown_content: str) -> List[Dict[str, Any]]:
    """
    Fallback parser that splits markdown by headers (# to ######) in pure Python.
    """
    lines = markdown_content.splitlines()
    parent_chunks = []
    
    current_headers = {}
    current_chunk_lines = []
    
    header_pattern = re.compile(r'^(#{1,6})\s+(.+)$')
    
    for line in lines:
        match = header_pattern.match(line.strip())
        if match:
            # Save the previous chunk if it has content
            if current_chunk_lines or current_headers:
                # Reconstruct header block
                header_lines = []
                for level in range(1, 7):
                    key = f"Header {level}"
                    if key in current_headers:
                        header_lines.append(f"{'#' * level} {current_headers[key]}")
                
                reconstructed_headers = "\n".join(header_lines)
                page_content = "\n".join(current_chunk_lines).strip()
                if reconstructed_headers:
                    full_content = f"{reconstructed_headers}\n\n{page_content}"
                else:
                    full_content = page_content
                    
                if page_content:
                    parent_chunks.append({
                        "header_path": current_headers.copy(),
                        "content": full_content
                    })
                current_chunk_lines = []
            
            # Update current headers
            hashes = match.group(1)
            level = len(hashes)
            title = match.group(2).strip()
            
            # Clear lower-level headers
            for l in range(level, 7):
                current_headers.pop(f"Header {l}", None)
            
            current_headers[f"Header {level}"] = title
        else:
            current_chunk_lines.append(line)
            
    # Add final chunk
    if current_chunk_lines or current_headers:
        header_lines = []
        for level in range(1, 7):
            key = f"Header {level}"
            if key in current_headers:
                header_lines.append(f"{'#' * level} {current_headers[key]}")
        
        reconstructed_headers = "\n".join(header_lines)
        page_content = "\n".join(current_chunk_lines).strip()
        if reconstructed_headers:
            full_content = f"{reconstructed_headers}\n\n{page_content}"
        else:
            full_content = page_content
            
        if page_content:
            parent_chunks.append({
                "header_path": current_headers.copy(),
                "content": full_content
            })
            
    return parent_chunks


def pure_python_character_split(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """
    Fallback splitter that performs character-based chunking with overlap in pure Python.
    """
    chunks = []
    text_len = len(text)
    step = chunk_size - chunk_overlap
    if step <= 0:
        step = chunk_size
        
    if text_len <= chunk_size:
        if text.strip():
            chunks.append(text)
        return chunks
        
    start = 0
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        if end >= text_len:
            break
        start += step
    return chunks


def chunk_markdown_content(
    markdown_content: str,
    filename: str,
    child_size: int = 200,
    child_overlap: int = 40,
    use_langchain: bool = True
) -> List[Dict[str, Any]]:
    """
    Splits a markdown text content into parent chunks based on headers,
    and then splits each parent chunk into child chunks with header path prefixes.

    Returns:
        List[Dict[str, Any]]: A list of child chunks ready to be written to a vector database.
    """
    # 2. Slice into Parent Chunks
    parent_chunks = []
    
    if use_langchain and HAS_LANGCHAIN:
        headers_to_split_on = [
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
            ("####", "Header 4"),
            ("#####", "Header 5"),
            ("######", "Header 6"),
        ]
        header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
        parent_docs = header_splitter.split_text(markdown_content)

        for doc in parent_docs:
            header_path = doc.metadata
            
            # Reconstruct the headers block to prepend to the content
            header_keys = ["Header 1", "Header 2", "Header 3", "Header 4", "Header 5", "Header 6"]
            header_symbols = ["#", "##", "###", "####", "#####", "######"]
            
            header_lines = []
            for key, symbol in zip(header_keys, header_symbols):
                if key in header_path:
                    header_lines.append(f"{symbol} {header_path[key]}")
            
            reconstructed_headers = "\n".join(header_lines)
            if reconstructed_headers:
                full_parent_content = f"{reconstructed_headers}\n\n{doc.page_content}"
            else:
                full_parent_content = doc.page_content

            parent_id = generate_parent_id(filename, header_path)
            parent_chunks.append({
                "parent_id": parent_id,
                "header_path": header_path,
                "content": full_parent_content
            })
    else:
        # Pure Python Fallback
        raw_parents = pure_python_markdown_split(markdown_content)
        for parent in raw_parents:
            parent_id = generate_parent_id(filename, parent["header_path"])
            parent_chunks.append({
                "parent_id": parent_id,
                "header_path": parent["header_path"],
                "content": parent["content"]
            })

    # 3. Slice into Child Chunks with Semantic Enhancement
    all_child_chunks = []

    if use_langchain and HAS_LANGCHAIN:
        child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_size,
            chunk_overlap=child_overlap,
            length_function=len
        )
    else:
        child_splitter = None

    for parent in parent_chunks:
        parent_id = parent["parent_id"]
        header_path = parent["header_path"]
        parent_content = parent["content"]

        # Split parent content into child snippets
        if child_splitter:
            child_texts = child_splitter.split_text(parent_content)
        else:
            child_texts = pure_python_character_split(
                parent_content, child_size, child_overlap
            )

        # Build semantic header prefix
        header_keys = ["Header 1", "Header 2", "Header 3", "Header 4", "Header 5", "Header 6"]
        path_list = [header_path[k] for k in header_keys if k in header_path]
        
        if path_list:
            header_prefix = f"[{' > '.join(path_list)}] "
        else:
            header_prefix = ""

        for child_text in child_texts:
            # Prepend header prefix to child content for semantic enhancement
            enhanced_content = f"{header_prefix}{child_text}"
            
            all_child_chunks.append({
                "child_content": enhanced_content,
                "metadata": {
                    "parent_id": parent_id,
                    "source_file": filename,
                    "header_path": header_path
                }
            })

    return all_child_chunks


def chunk_markdown_file(
    file_path: str,
    child_size: int = 200,
    child_overlap: int = 40,
    use_langchain: bool = True
) -> List[Dict[str, Any]]:
    """
    Reads a markdown file, splits it into parent chunks based on headers,
    and then splits each parent chunk into child chunks with header path prefixes.

    Returns:
        List[Dict[str, Any]]: A list of child chunks ready to be written to a vector database.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    filename = os.path.basename(file_path)

    # 1. Read Markdown content
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        markdown_content = f.read()

    return chunk_markdown_content(
        markdown_content=markdown_content,
        filename=filename,
        child_size=child_size,
        child_overlap=child_overlap,
        use_langchain=use_langchain
    )



# Example usage
if __name__ == "__main__":
    # Create a dummy markdown file to test
    dummy_md = "test_doc.md"
    dummy_content = """# 系統架構
這是系統架構的總覽介紹。我們的系統包含前端與後端。

## 資料庫設計
資料庫採用 MongoDB 作為應用資料庫，Qdrant 作為向量資料庫。
- MongoDB 用於儲存使用者與對話紀錄。
- Qdrant 用於儲存向量索引。

## API 設計
### 檔案上傳 API
提供 /api/embedding/upload 接口進行檔案上傳。
"""
    with open(dummy_md, "w", encoding="utf-8") as f:
        f.write(dummy_content)

    print("--- 測試切分 Dummy Markdown 檔案 (使用 Pure Python 模式) ---")
    try:
        chunks = chunk_markdown_file(dummy_md, child_size=150, child_overlap=30, use_langchain=False)
        for idx, chunk in enumerate(chunks):
            print(f"\n[Chunk {idx+1}]")
            print(f"Content: {chunk['child_content']}")
            print(f"Metadata: {chunk['metadata']}")
    except Exception as e:
        print(f"Error: {e}")
        
    if HAS_LANGCHAIN:
        print("\n--- 測試切分 Dummy Markdown 檔案 (使用 LangChain 模式) ---")
        try:
            chunks_lc = chunk_markdown_file(dummy_md, child_size=150, child_overlap=30, use_langchain=True)
            for idx, chunk in enumerate(chunks_lc):
                print(f"\n[Chunk {idx+1} - LangChain]")
                print(f"Content: {chunk['child_content']}")
                print(f"Metadata: {chunk['metadata']}")
        except Exception as e:
            print(f"Error: {e}")

    if os.path.exists(dummy_md):
        os.remove(dummy_md)
