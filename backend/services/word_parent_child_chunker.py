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


def parse_doc_to_markdown(doc_bytes: bytes, filename: str) -> str:
    """
    Parses legacy Word .doc files into Markdown format.
    Gracefully falls back across textract, pypandoc, comtypes, and binary string extraction.
    """
    import tempfile
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    temp_dir = os.path.join(current_dir, "../temp")
    os.makedirs(temp_dir, exist_ok=True)
    
    temp_fd, temp_path = tempfile.mkstemp(suffix=".doc", dir=temp_dir)
    try:
        with os.fdopen(temp_fd, 'wb') as tmp:
            tmp.write(doc_bytes)
        
        # 1. Try textract
        try:
            import textract
            text_bytes = textract.process(temp_path)
            return text_bytes.decode('utf-8', errors='ignore').strip()
        except Exception as e:
            logger.debug(f"textract failed: {e}")
            
        # 2. Try pypandoc
        try:
            import pypandoc
            output = pypandoc.convert_file(temp_path, 'markdown', format='doc')
            return output.strip()
        except Exception as e:
            logger.debug(f"pypandoc failed: {e}")
            
        # 3. Try comtypes Word Automation (Windows only)
        if os.name == 'nt':
            try:
                import comtypes.client
                word = comtypes.client.CreateObject('Word.Application')
                word.Visible = False
                doc = word.Documents.Open(temp_path)
                docx_path = temp_path + "x"
                doc.SaveAs(docx_path, FileFormat=16) # 16 is wdFormatXMLDocument
                doc.Close()
                word.Quit()
                
                if os.path.exists(docx_path):
                    with open(docx_path, "rb") as df:
                        docx_bytes = df.read()
                    os.remove(docx_path)
                    return parse_docx_to_markdown(docx_bytes)
            except Exception as e:
                logger.debug(f"comtypes Word automation failed: {e}")
                
        # 4. Binary text extraction fallback
        logger.warning(f"All standard doc parsers failed for {filename}. Using basic binary text extraction fallback.")
        import string
        printable = set(string.printable)
        text_chars = []
        for b in doc_bytes:
            c = chr(b)
            if c in printable or b >= 128:
                text_chars.append(c)
        extracted = "".join(text_chars)
        cleaned = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', extracted)
        lines = [line.strip() for line in cleaned.split('\n') if len(line.strip()) > 3]
        return "\n\n".join(lines)
        
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


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
