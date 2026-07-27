import io
import os
import re
import logging
from typing import List, Dict, Any
import docx
from services.markdown_parent_child_chunker import chunk_markdown_content

logger = logging.getLogger("airag.word_chunker")


def iter_block_items(parent):
    """
    Yield each paragraph and table child within parent, in document order.
    """
    from docx.document import Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    if isinstance(parent, Document):
        parent_elm = parent.element.body
    else:
        parent_elm = parent._element

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def get_heading_level(paragraph) -> int:
    """
    Detects heading level of a python-docx paragraph using standard Word styles,
    outline levels, and custom smart heuristics (for non-standard documents).
    Returns 0 if it is not a heading.
    """
    style_name = paragraph.style.name if paragraph.style else ""
    if style_name:
        # Match styles like 'Heading 1', 'heading 2', 'Heading1', etc.
        match = re.match(r'^[Hh]eading\s*(\d+)$', style_name.strip())
        if match:
            return int(match.group(1))
    
    # Fallback to outline level if set in paragraph format
    try:
        outline_level = paragraph.paragraph_format.outline_level
        if outline_level is not None and outline_level < 9:
            return outline_level + 1
    except Exception:
        pass
        
    # Heuristics based on text patterns (e.g. 一、, 1.1, 第一章)
    text = paragraph.text.strip()
    if not text:
        return 0
        
    # Pattern 1: 第一章, 第一節, etc. (Level 1)
    if re.search(r'^第[一二三四五六七八九十廿卅]+[章節](\s+.+)?$', text):
        return 1
        
    # Pattern 2: 一、, 二、, etc. (Level 1)
    if re.match(r'^[一二三四五六七八九十百]+、.+', text):
        return 1
        
    # Pattern 3: 1.1, 1.2, 2.1 (Level 2)
    if re.match(r'^\d+\.\d+(\s+.+)?$', text):
        return 2
        
    # Pattern 4: 1.1.1, 1.1.2 (Level 3)
    if re.match(r'^\d+\.\d+\.\d+(\s+.+)?$', text):
        return 3
        
    # Pattern 5: (一), (二), （一）, （二） (Level 2)
    if re.match(r'^[（(][一二三四五六七八九十]+[）)](\s+.+)?$', text):
        return 2
        
    # Heuristics based on bold formatting and text length
    if len(text) >= 2 and len(text) <= 50:
        # Avoid lines ending with common sentence punctuations
        if not text.endswith(('.', '。', '，', ',', '；', ';', '：', ':', '！', '!')):
            if paragraph.runs:
                has_bold = False
                all_bold_or_none = True
                for run in paragraph.runs:
                    if run.text.strip():
                        if run.bold:
                            has_bold = True
                        elif run.bold is False:
                            all_bold_or_none = False
                            break
                if has_bold and all_bold_or_none:
                    return 2
                    
    return 0


def table_to_markdown(table) -> str:
    """
    Converts a python-docx Table into a Markdown table string.
    """
    rows = []
    for i, row in enumerate(table.rows):
        cells = [cell.text.replace("\n", " ").strip() for cell in row.cells]
        if not any(cells):
            continue
        rows.append("| " + " | ".join(cells) + " |")
        if i == 0:
            # Header separator
            seps = ["---" for _ in cells]
            rows.append("| " + " | ".join(seps) + " |")
    return "\n".join(rows)


def get_paragraph_text(paragraph) -> str:
    """
    Extracts text of a python-docx paragraph and formats lists as Markdown lists.
    """
    text = paragraph.text.strip()
    if not text:
        return ""
    
    style_name = paragraph.style.name.lower() if paragraph.style else ""
    if "bullet" in style_name:
        return f"* {text}"
    elif "number" in style_name or "num" in style_name:
        return f"1. {text}"
    
    return text


def parse_docx_to_markdown(docx_bytes: bytes) -> str:
    """
    Parses a DOCX or DOTX document from bytes and returns a structured Markdown string.
    """
    doc = docx.Document(io.BytesIO(docx_bytes))
    markdown_parts = []
    
    for item in iter_block_items(doc):
        if isinstance(item, docx.text.paragraph.Paragraph):
            heading_level = get_heading_level(item)
            text = get_paragraph_text(item)
            if not text:
                continue
                
            if heading_level > 0:
                markdown_parts.append(f"\n" + ("#" * heading_level) + f" {text}\n")
            else:
                markdown_parts.append(text)
        elif isinstance(item, docx.table.Table):
            table_md = table_to_markdown(item)
            if table_md:
                markdown_parts.append(f"\n{table_md}\n")
                
    return "\n\n".join(markdown_parts).strip()


def _extract_doc_pieces(doc_bytes: bytes) -> str:
    """
    Extracts the raw text of a legacy Word .doc (OLE2 Compound File) by walking the
    FIB piece table (MS-DOC 規格的 Clx / PlcPcd)，回傳含 Word 控制字元的原始文字。

    每個 piece 的 fc 若帶有 0x40000000 旗標代表以單位元組（文件 code page）儲存，
    否則為 UTF-16LE。中文 .doc 多為 UTF-16LE，單位元組時優先以 cp950 解碼。
    """
    import struct

    import olefile

    with olefile.OleFileIO(io.BytesIO(doc_bytes)) as ole:
        if not ole.exists("WordDocument"):
            raise ValueError("OLE2 檔案內找不到 WordDocument stream，可能不是 Word .doc 檔")
        word_stream = ole.openstream("WordDocument").read()

        # FIB base 的 flags（offset 0x000A）第 9 個 bit 決定 table stream 是 1Table 還是 0Table
        flags = struct.unpack_from("<H", word_stream, 0x000A)[0]
        table_name = "1Table" if (flags & 0x0200) else "0Table"
        if not ole.exists(table_name):
            raise ValueError(f"OLE2 檔案內找不到 {table_name} stream，無法取得 piece table")
        table_stream = ole.openstream(table_name).read()

    # FibRgFcLcb97 中 fcClx / lcbClx 的固定位移
    fc_clx, lcb_clx = struct.unpack_from("<iI", word_stream, 0x01A2)
    clx = table_stream[fc_clx:fc_clx + lcb_clx]

    # Clx = 若干個 Prc（0x01）後接唯一一個 Pcdt（0x02），Pcdt 內才是 PlcPcd
    plc_pcd = None
    pos = 0
    while pos < len(clx):
        if clx[pos] == 0x01:
            cb_grpprl = struct.unpack_from("<H", clx, pos + 1)[0]
            pos += 3 + cb_grpprl
        elif clx[pos] == 0x02:
            lcb = struct.unpack_from("<I", clx, pos + 1)[0]
            plc_pcd = clx[pos + 5:pos + 5 + lcb]
            break
        else:
            break
    if not plc_pcd or len(plc_pcd) < 16:
        raise ValueError("解析 .doc piece table 失敗（Clx 內找不到有效的 PlcPcd）")

    # PlcPcd = (n+1) 個 CP（各 4 bytes）後接 n 個 PCD（各 8 bytes）
    piece_count = (len(plc_pcd) - 4) // 12
    cps = struct.unpack_from(f"<{piece_count + 1}I", plc_pcd, 0)

    parts = []
    for i in range(piece_count):
        pcd_offset = 4 * (piece_count + 1) + 8 * i
        fc = struct.unpack_from("<I", plc_pcd, pcd_offset + 2)[0]
        is_single_byte = bool(fc & 0x40000000)
        fc &= 0x3FFFFFFF
        char_count = cps[i + 1] - cps[i]
        if char_count <= 0:
            continue
        if is_single_byte:
            raw = word_stream[fc // 2: fc // 2 + char_count]
            try:
                parts.append(raw.decode("cp950"))
            except UnicodeDecodeError:
                parts.append(raw.decode("cp1252", errors="ignore"))
        else:
            raw = word_stream[fc: fc + char_count * 2]
            parts.append(raw.decode("utf-16-le", errors="ignore"))

    return "".join(parts)


def _clean_doc_text(raw_text: str) -> str:
    """
    將 .doc piece 的原始文字中的 Word 控制字元轉為純文字：
    移除功能代碼（field instruction，例如 HYPERLINK "..."）只保留顯示結果，
    表格儲存格結束、換行、分頁符號統一轉為換行，其餘控制字元去除。
    """
    # \x13 field begin ... \x14 separator ... \x15 field end：只保留 separator 之後的顯示文字
    raw_text = re.sub(r"\x13[^\x14\x15]*\x14?", "", raw_text)
    raw_text = raw_text.replace("\x15", "")
    # \x07 儲存格/列結束、\x0b 手動換行、\x0c 分頁、\r 段落結束
    for ch in ("\x07", "\x0b", "\x0c", "\r"):
        raw_text = raw_text.replace(ch, "\n")
    raw_text = re.sub(r"[\x00-\x08\x0e-\x1f]", "", raw_text)
    lines = [line.strip() for line in raw_text.split("\n")]
    return "\n".join(line for line in lines if line)


def parse_doc_to_markdown(doc_bytes: bytes, filename: str) -> str:
    """
    Parses legacy Word .doc files into plain text / Markdown format.
    以 OLE2 piece table 直接解析（可正確處理中文 UTF-16LE 與 cp950 內容）；
    若檔案其實是被改名的 .docx（zip）則轉交 parse_docx_to_markdown。
    解析失敗時直接拋出例外，不再回退到二進位字串擷取（會產生亂碼並污染向量庫）。
    """
    if doc_bytes[:2] == b"PK":
        logger.info(f"{filename} 副檔名為 .doc 但實際為 OOXML（zip）格式，改用 docx 解析")
        return parse_docx_to_markdown(doc_bytes)

    if doc_bytes[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError(
            f"{filename} 不是有效的 Word .doc（OLE2）檔案，若為 RTF 或 HTML 另存的檔案請先轉存為 .docx"
        )

    try:
        text = _clean_doc_text(_extract_doc_pieces(doc_bytes))
    except Exception as e:
        logger.error(f"Error parsing DOC {filename}: {type(e).__name__}: {e}")
        raise ValueError(f"DOC 解析失敗: {e}") from e

    if not text.strip():
        raise ValueError(f"DOC 解析後內容為空: {filename}")

    return text


def chunk_word_content(
    file_bytes: bytes,
    filename: str,
    child_size: int = 200,
    child_overlap: int = 40
) -> List[Dict[str, Any]]:
    """
    Parses word file content (bytes) into Markdown, then splits it into 
    parent-child chunks using the markdown splitter.
    """
    ext = filename.split(".")[-1].lower()
    
    if ext in ["docx", "dotx"]:
        markdown_content = parse_docx_to_markdown(file_bytes)
    elif ext == "doc":
        markdown_content = parse_doc_to_markdown(file_bytes, filename)
    else:
        raise ValueError(f"Unsupported word file extension: .{ext}")
        
    # Reuse chunk_markdown_content for parent-child structural splitting
    chunks = chunk_markdown_content(
        markdown_content=markdown_content,
        filename=filename,
        child_size=child_size,
        child_overlap=child_overlap,
        use_langchain=True
    )
    
    # Inject file_type to metadata
    for chunk in chunks:
        chunk["metadata"]["file_type"] = ext
        
    return chunks


def chunk_word_file(
    file_path: str,
    child_size: int = 200,
    child_overlap: int = 40
) -> List[Dict[str, Any]]:
    """
    Reads a word file from disk, parses it to Markdown, and splits it into parent-child chunks.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        file_bytes = f.read()
        
    return chunk_word_content(
        file_bytes=file_bytes,
        filename=filename,
        child_size=child_size,
        child_overlap=child_overlap
    )
