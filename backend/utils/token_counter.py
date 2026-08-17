import tiktoken

_encoding = tiktoken.get_encoding("cl100k_base")

def count_tokens(text: str) -> int:
    """
    使用 tiktoken (cl100k_base) 估算文字的 token 數。
    """
    if not text:
        return 0
    return len(_encoding.encode(text))


def split_text_by_tokens(text: str, max_tokens: int) -> list[str]:
    """
    將文字依 token 數切成多段，每段不超過 max_tokens。

    只 encode 一次再對 token 序列切片後 decode，避免對超長文字反覆 encode。
    cl100k_base 下一個中文字通常由多個 token 組成，切點可能落在單一字元中間，
    decode 會在邊界產生替代字元 U+FFFD，這裡直接去除（僅損失邊界的 1 個字）。
    """
    if not text:
        return []
    if max_tokens <= 0:
        return [text]

    tokens = _encoding.encode(text)
    if len(tokens) <= max_tokens:
        return [text]

    pieces = []
    for start in range(0, len(tokens), max_tokens):
        piece = _encoding.decode(tokens[start:start + max_tokens]).strip("�")
        if piece:
            pieces.append(piece)
    return pieces
