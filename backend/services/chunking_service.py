import re
from typing import List, Dict, Any

class ChunkingService:
    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        估算文本的 Token 數量。
        繁體中文/CJK 約 0.8 token/字，英文/數字約 1.3 token/單字。
        """
        if not text:
            return 0
        english_words = len(re.findall(r'\b[a-zA-Z0-9]+\b', text))
        cjk_chars = len(re.findall(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', text))
        other_chars = len(text) - (english_words * 4) - cjk_chars
        
        estimated = int(cjk_chars * 0.85 + english_words * 1.3 + other_chars * 0.3)
        return max(1, estimated)

    @classmethod
    def split_text(
        cls, 
        text: str, 
        chunk_size: int = 512, 
        chunk_overlap: int = 50, 
        separator: str = "\n\n"
    ) -> List[Dict[str, Any]]:
        """
        將文本依據指定分隔符號、大小及重疊量進行切分。
        """
        if not text:
            return []
        
        if not separator:
            separator = "\n"
            
        parts = text.split(separator)
        chunks = []
        current_chunk = []
        current_len = 0
        chunk_index = 0
        start_char = 0
        
        i = 0
        while i < len(parts):
            part = parts[i]
            part_len = len(part)
            
            # 若單個段落長度直接大於 chunk_size，需強行按字元大小切分
            if part_len > chunk_size:
                # 先清空目前的 buffer
                if current_chunk:
                    content = separator.join(current_chunk)
                    end_char = start_char + len(content)
                    chunks.append({
                        "index": chunk_index,
                        "content": content,
                        "token_count": cls.estimate_tokens(content),
                        "char_count": len(content),
                        "start_char": start_char,
                        "end_char": end_char
                    })
                    chunk_index += 1
                    start_char += len(content) + len(separator)
                    current_chunk = []
                    current_len = 0
                
                # 開始切割超長段落
                for j in range(0, part_len, chunk_size - chunk_overlap):
                    sub_part = part[j : j + chunk_size]
                    sub_start = start_char + j
                    sub_end = sub_start + len(sub_part)
                    chunks.append({
                        "index": chunk_index,
                        "content": sub_part,
                        "token_count": cls.estimate_tokens(sub_part),
                        "char_count": len(sub_part),
                        "start_char": sub_start,
                        "end_char": sub_end
                    })
                    chunk_index += 1
                
                start_char += part_len + len(separator)
                i += 1
                continue
            
            # 判斷加入此段落後是否會超出限制
            added_len = part_len + (len(separator) if current_chunk else 0)
            if current_len + added_len <= chunk_size:
                current_chunk.append(part)
                current_len += added_len
                i += 1
            else:
                # 超過限制，輸出目前區塊
                content = separator.join(current_chunk)
                end_char = start_char + len(content)
                chunks.append({
                    "index": chunk_index,
                    "content": content,
                    "token_count": cls.estimate_tokens(content),
                    "char_count": len(content),
                    "start_char": start_char,
                    "end_char": end_char
                })
                chunk_index += 1
                
                # 計算重疊段落 (overlap)
                overlap_len = 0
                backtrace_count = 0
                for r_part in reversed(current_chunk):
                    if overlap_len + len(r_part) + len(separator) <= chunk_overlap:
                        overlap_len += len(r_part) + len(separator)
                        backtrace_count += 1
                    else:
                        break
                
                # 新的開始位置為上一區塊的結尾扣除重疊長度
                non_overlap_content = separator.join(current_chunk[:-backtrace_count]) if backtrace_count > 0 else content
                start_char += len(non_overlap_content) + len(separator)
                
                if backtrace_count > 0:
                    current_chunk = current_chunk[-backtrace_count:]
                    current_len = sum(len(p) for p in current_chunk) + len(separator) * (len(current_chunk) - 1)
                else:
                    current_chunk = []
                    current_len = 0
        
        # 輸出最後殘餘區塊
        if current_chunk:
            content = separator.join(current_chunk)
            end_char = start_char + len(content)
            chunks.append({
                "index": chunk_index,
                "content": content,
                "token_count": cls.estimate_tokens(content),
                "char_count": len(content),
                "start_char": start_char,
                "end_char": end_char
            })
            
        return chunks
