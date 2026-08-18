#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
PDF Parent-Child Chunking Service.

PDF 經 fitz 取出的是沒有 markdown 標題的純文字，交給 markdown_parent_child_chunker 會讓
MarkdownHeaderTextSplitter 回傳單一 doc，整份文件因此算出同一個 parent_id
（見 docs/DevelopmentProcess/BugFix.md 2026-08-17）。

這裡改以「頁面」作為父段落的自然邊界，並一律套用 token 上限：
- 單頁太小 → 連續數頁聚合成一個父段落（PARENT_MAX_TOKENS / PDF_PARENT_MAX_PAGES 先到者為準）。
- 單頁太大 → 於行邊界切成多個父段落，避免任何一個父段落大到還原時撐爆脈絡。

拿不到頁面結構時（例如 /api/embedding/chunk 只收得到純文字）退化為純 token 預算切分，
仍能保證父段落有界，只是失去頁碼。
"""

import hashlib
from typing import List, Dict, Any, Optional

from config import settings
from utils.token_counter import count_tokens, split_text_by_tokens
from services.markdown_parent_child_chunker import pure_python_character_split

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False


_HEADER_KEYS = ["Header 1", "Header 2", "Header 3", "Header 4", "Header 5", "Header 6"]


def generate_pdf_parent_id(filename: str, part_key: str) -> str:
    """
    產生 PDF 父段落 ID。刻意沿用 markdown_parent_child_chunker.generate_parent_id 的
    `{filename}_{md5前12碼}` 格式，下游只做等值比對，不必為 PDF 另外處理。
    """
    hash_val = hashlib.md5(f"{filename}_{part_key}".encode("utf-8")).hexdigest()[:12]
    return f"{filename}_{hash_val}"


def split_by_token_budget(text: str, max_tokens: int) -> List[str]:
    """
    以行為邊界把文字打包成不超過 max_tokens 的區塊。

    單行本身就超過預算時（PDF 常見的整段不換行）才退回 token 硬切，
    確保任何輸入都不會產出超出預算的區塊。
    """
    if max_tokens <= 0 or not text.strip():
        return [text] if text.strip() else []
    if count_tokens(text) <= max_tokens:
        return [text]

    parts: List[str] = []
    buffer: List[str] = []
    buffer_tokens = 0

    def flush():
        nonlocal buffer, buffer_tokens
        if buffer:
            joined = "\n".join(buffer).strip()
            if joined:
                parts.append(joined)
        buffer = []
        buffer_tokens = 0

    for line in text.split("\n"):
        line_tokens = count_tokens(line)
        if line_tokens > max_tokens:
            flush()
            parts.extend(split_text_by_tokens(line, max_tokens))
            continue
        if buffer and buffer_tokens + line_tokens > max_tokens:
            flush()
        buffer.append(line)
        buffer_tokens += line_tokens

    flush()
    return parts


def build_pdf_parents(
    pages: List[str],
    filename: str,
    parent_max_tokens: Optional[int] = None,
    max_pages_per_parent: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    把逐頁文字聚合成父段落清單，每筆為
    {parent_id, content, start_page, end_page, section}（頁碼由 1 起算）。
    """
    budget = settings.PARENT_MAX_TOKENS if parent_max_tokens is None else parent_max_tokens
    max_pages = settings.PDF_PARENT_MAX_PAGES if max_pages_per_parent is None else max_pages_per_parent
    if max_pages <= 0:
        max_pages = len(pages) or 1

    raw_parents: List[Dict[str, Any]] = []
    buffer: List[str] = []
    buffer_tokens = 0
    buffer_start_page = 1

    def flush(end_page: int):
        nonlocal buffer, buffer_tokens
        if buffer:
            content = "\n".join(buffer).strip()
            if content:
                raw_parents.append({
                    "content": content,
                    "start_page": buffer_start_page,
                    "end_page": end_page
                })
        buffer = []
        buffer_tokens = 0

    for page_idx, page_text in enumerate(pages):
        page_no = page_idx + 1
        page_text = (page_text or "").strip()
        if not page_text:
            continue

        page_tokens = count_tokens(page_text)

        # 單頁就超過預算：先收掉前面累積的頁面，再把這一頁自己切成多個父段落
        if budget > 0 and page_tokens > budget:
            flush(page_no - 1 if page_no > buffer_start_page else buffer_start_page)
            for part in split_by_token_budget(page_text, budget):
                raw_parents.append({
                    "content": part,
                    "start_page": page_no,
                    "end_page": page_no
                })
            buffer_start_page = page_no + 1
            continue

        if buffer and (
            (budget > 0 and buffer_tokens + page_tokens > budget)
            or len(buffer) >= max_pages
        ):
            flush(page_no - 1)
            buffer_start_page = page_no

        if not buffer:
            buffer_start_page = page_no
        buffer.append(page_text)
        buffer_tokens += page_tokens

    flush(len(pages))

    # 同一頁被切成多段時 part_key 需帶序號，否則 parent_id 會撞在一起
    parents: List[Dict[str, Any]] = []
    seen_keys: Dict[str, int] = {}
    for parent in raw_parents:
        start_page = parent["start_page"]
        end_page = max(parent["end_page"], start_page)
        base_key = f"p{start_page}-{end_page}"
        seq = seen_keys.get(base_key, 0)
        seen_keys[base_key] = seq + 1
        part_key = base_key if seq == 0 else f"{base_key}#{seq}"

        section = f"第 {start_page} 頁" if start_page == end_page else f"第 {start_page}-{end_page} 頁"
        parents.append({
            "parent_id": generate_pdf_parent_id(filename, part_key),
            "content": parent["content"],
            "start_page": start_page,
            "end_page": end_page,
            "section": section
        })
    return parents


# --- 字級啟發式標題偵測 ---
# 標題行的長度上限（字元）。PDF 的標題不會是整段文字，過長者多半是被放大的引言或表格內容
_MAX_HEADING_CHARS = 80
# 偵測結果的合理範圍：標題佔比過高代表「字級判準」在這份文件上失準（例如整份都是大字），
# 反而會把每一行都切成獨立父段落，此時寧可退回頁面模式
_MAX_HEADING_RATIO = 0.2
# 至少要偵測到幾個標題才認定這份 PDF 真的有標題階層
_MIN_HEADINGS = 3


def detect_body_size(pages_lines: List[List[Dict[str, Any]]]) -> float:
    """
    以「字元數加權」找出內文字級：出現最多字的那個字級就是內文，其餘偏大者才可能是標題。
    用行數加權會被大量的短行（頁首頁尾、表格欄位）帶偏。
    """
    weights: Dict[float, int] = {}
    for lines in pages_lines:
        for line in lines:
            size = round(line["size"] * 2) / 2  # 取到 0.5 級距，吸收微小浮點差異
            weights[size] = weights.get(size, 0) + len(line["text"].strip())
    if not weights:
        return 0.0
    return max(weights.items(), key=lambda kv: kv[1])[0]


def detect_heading_levels(
    pages_lines: List[List[Dict[str, Any]]],
    size_ratio: Optional[float] = None
) -> Dict[float, int]:
    """
    回傳「字級 -> 標題層級（1~6）」的對照表；字級由大到小依序對應 Header 1~6。
    偵測不到可用的標題階層時回傳空 dict，呼叫端據此退回頁面模式。
    """
    ratio = settings.PDF_HEADING_SIZE_RATIO if size_ratio is None else size_ratio
    body_size = detect_body_size(pages_lines)
    if body_size <= 0:
        return {}

    heading_sizes: Dict[float, int] = {}
    total_lines = 0
    heading_lines = 0
    for lines in pages_lines:
        for line in lines:
            total_lines += 1
            text = line["text"].strip()
            if not text or len(text) > _MAX_HEADING_CHARS:
                continue
            size = round(line["size"] * 2) / 2
            # 明顯大於內文，或「與內文同級但粗體」的短行
            if size >= body_size * ratio or (line["bold"] and size >= body_size):
                heading_sizes[size] = heading_sizes.get(size, 0) + 1
                heading_lines += 1

    if heading_lines < _MIN_HEADINGS or total_lines == 0:
        return {}
    if heading_lines / total_lines > _MAX_HEADING_RATIO:
        return {}

    # 字級由大到小對應 Header 1~6，超過 6 種字級的部分一律歸到 Header 6
    ordered = sorted(heading_sizes.keys(), reverse=True)
    return {size: min(level + 1, 6) for level, size in enumerate(ordered)}


def build_pdf_parents_by_heading(
    pages_lines: List[List[Dict[str, Any]]],
    filename: str,
    parent_max_tokens: Optional[int] = None,
    size_ratio: Optional[float] = None
) -> Optional[List[Dict[str, Any]]]:
    """
    以偵測到的標題階層切出父段落，回傳格式與 build_pdf_parents() 相同並額外帶 `header_path`。

    偵測不到標題階層（掃描檔、排版無字級變化、或判準失準）時回傳 None，
    由呼叫端退回頁面模式——**不硬湊**，寧可用可靠的頁面邊界。
    """
    budget = settings.PARENT_MAX_TOKENS if parent_max_tokens is None else parent_max_tokens
    level_map = detect_heading_levels(pages_lines, size_ratio)
    if not level_map:
        return None

    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    header_stack: Dict[str, str] = {}

    for page_idx, lines in enumerate(pages_lines):
        page_no = page_idx + 1
        for line in lines:
            text = line["text"].strip()
            if not text:
                continue
            size = round(line["size"] * 2) / 2
            level = level_map.get(size)
            is_heading = level is not None and len(text) <= _MAX_HEADING_CHARS

            if is_heading:
                # 進入新標題：清掉同級與更低階的舊標題，再記錄自己
                for lower in range(level, 7):
                    header_stack.pop(f"Header {lower}", None)
                header_stack[f"Header {level}"] = text
                current = {
                    "lines": [text],
                    "header_path": dict(header_stack),
                    "start_page": page_no,
                    "end_page": page_no
                }
                sections.append(current)
                continue

            if current is None:
                # 第一個標題出現之前的前言（封面、目次）自成一段
                current = {
                    "lines": [],
                    "header_path": {},
                    "start_page": page_no,
                    "end_page": page_no
                }
                sections.append(current)
            current["lines"].append(text)
            current["end_page"] = page_no

    parents: List[Dict[str, Any]] = []
    seen_keys: Dict[str, int] = {}
    for section in sections:
        content = "\n".join(section["lines"]).strip()
        if not content:
            continue

        header_path = section["header_path"]
        path_list = [header_path[k] for k in _HEADER_KEYS if k in header_path]
        path_str = " > ".join(path_list)
        base_key = f"h:{path_str}" if path_str else f"h:preface:p{section['start_page']}"

        # 單一標題底下的內容仍可能過長（例如只有一層標題的長章節），一律套用 token 上限
        for part in split_by_token_budget(content, budget):
            seq = seen_keys.get(base_key, 0)
            seen_keys[base_key] = seq + 1
            part_key = base_key if seq == 0 else f"{base_key}#{seq}"
            parents.append({
                "parent_id": generate_pdf_parent_id(filename, part_key),
                "content": part,
                "start_page": section["start_page"],
                "end_page": max(section["end_page"], section["start_page"]),
                "section": path_str,
                "header_path": header_path
            })

    return parents or None


def chunk_pdf_lines(
    pages_lines: List[List[Dict[str, Any]]],
    filename: str,
    child_size: int = 512,
    child_overlap: int = 50,
    parent_max_tokens: Optional[int] = None,
    max_pages_per_parent: Optional[int] = None,
    use_langchain: bool = True
) -> List[Dict[str, Any]]:
    """
    PDF 切分的主要入口：優先用字級偵測出的標題階層切父段落，
    偵測不到才退回以頁面為邊界（build_pdf_parents）。

    有標題階層時，子段落會比照 markdown 切分器加上 `[標題路徑] ` 語意前綴。
    """
    parents = None
    if settings.PDF_HEADING_DETECTION:
        parents = build_pdf_parents_by_heading(
            pages_lines=pages_lines,
            filename=filename,
            parent_max_tokens=parent_max_tokens
        )

    if parents is None:
        pages = ["\n".join(line["text"] for line in lines) for lines in pages_lines]
        parents = build_pdf_parents(
            pages=pages,
            filename=filename,
            parent_max_tokens=parent_max_tokens,
            max_pages_per_parent=max_pages_per_parent
        )

    return _parents_to_children(parents, filename, child_size, child_overlap, use_langchain)


def chunk_pdf_pages(
    pages: List[str],
    filename: str,
    child_size: int = 512,
    child_overlap: int = 50,
    parent_max_tokens: Optional[int] = None,
    max_pages_per_parent: Optional[int] = None,
    use_langchain: bool = True
) -> List[Dict[str, Any]]:
    """
    將逐頁 PDF 文字切成 Child Chunks，回傳格式與 chunk_markdown_content 一致
    （`child_content` + `metadata`），呼叫端不需要為 PDF 另外分支。

    metadata 額外帶 `page`（該父段落的起始頁）與 `section`（頁碼範圍），
    讓 payload 的 page 欄位終於是真實頁碼而非寫死的 1。
    """
    parents = build_pdf_parents(
        pages=pages,
        filename=filename,
        parent_max_tokens=parent_max_tokens,
        max_pages_per_parent=max_pages_per_parent
    )
    return _parents_to_children(parents, filename, child_size, child_overlap, use_langchain)


def _parents_to_children(
    parents: List[Dict[str, Any]],
    filename: str,
    child_size: int,
    child_overlap: int,
    use_langchain: bool
) -> List[Dict[str, Any]]:
    """
    把父段落切成 Child Chunks。父段落帶 `header_path` 時，比照 markdown 切分器
    為每個子段落加上 `[標題路徑] ` 語意前綴，提升向量檢索時的脈絡辨識度。
    """
    if use_langchain and HAS_LANGCHAIN:
        child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_size,
            chunk_overlap=child_overlap,
            length_function=len
        )
    else:
        child_splitter = None

    all_children: List[Dict[str, Any]] = []
    for parent in parents:
        if child_splitter:
            child_texts = child_splitter.split_text(parent["content"])
        else:
            child_texts = pure_python_character_split(parent["content"], child_size, child_overlap)

        header_path = parent.get("header_path") or {}
        path_list = [header_path[k] for k in _HEADER_KEYS if k in header_path]
        header_prefix = f"[{' > '.join(path_list)}] " if path_list else ""

        for child_text in child_texts:
            if not child_text.strip():
                continue
            all_children.append({
                "child_content": f"{header_prefix}{child_text}",
                "metadata": {
                    "parent_id": parent["parent_id"],
                    "source_file": filename,
                    "page": parent["start_page"],
                    # 父段落可能橫跨數頁，只留 start_page 的話，落在中間頁的圖片就反查不到自己
                    # 屬於哪個父段落（見 IngestService._process_upsert 的 page_to_parent）
                    "end_page": parent["end_page"],
                    "section": parent["section"],
                    "header_path": header_path
                }
            })
    return all_children


def chunk_pdf_text(
    text: str,
    filename: str,
    child_size: int = 512,
    child_overlap: int = 50,
    parent_max_tokens: Optional[int] = None,
    use_langchain: bool = True
) -> List[Dict[str, Any]]:
    """
    只拿得到純文字（沒有頁面結構）時的入口：以 token 預算切出父段落。
    頁碼一律為 1——寧可誠實標成第 1 頁，也不要編造頁碼。
    """
    budget = settings.PARENT_MAX_TOKENS if parent_max_tokens is None else parent_max_tokens
    pseudo_pages = split_by_token_budget(text, budget) if budget > 0 else [text]

    parents_as_pages = [p for p in pseudo_pages if p.strip()]
    children = chunk_pdf_pages(
        pages=parents_as_pages,
        filename=filename,
        child_size=child_size,
        child_overlap=child_overlap,
        parent_max_tokens=parent_max_tokens,
        max_pages_per_parent=1,
        use_langchain=use_langchain
    )
    for child in children:
        child["metadata"]["page"] = 1
        child["metadata"]["end_page"] = 1
        child["metadata"]["section"] = ""
    return children
