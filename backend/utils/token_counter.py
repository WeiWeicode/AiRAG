import tiktoken

_encoding = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    """
    使用 tiktoken (cl100k_base) 估算文字的 token 數。
    """
    if not text:
        return 0
    return len(_encoding.encode(text))
