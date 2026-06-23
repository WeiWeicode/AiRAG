import httpx
import logging
from typing import List, Dict, Any, AsyncGenerator
from config import settings

logger = logging.getLogger("airag.llm")

class LLMService:
    @classmethod
    async def chat_completion(
        cls, 
        messages: List[Dict[str, str]], 
        temperature: float = 0.7, 
        max_tokens: int = 1024,
        stream: bool = False
    ) -> Any:
        """
        向 vLLM /chat/completions 發送請求。
        """
        url = f"{settings.VLLM_BASE_URL.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": settings.VLLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }
        
        try:
            client = httpx.AsyncClient(timeout=60.0)
            if stream:
                # 串流模式返回生成器
                async def stream_generator() -> AsyncGenerator[str, None]:
                    try:
                        async with client.stream("POST", url, headers=headers, json=payload) as response:
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line.strip():
                                    continue
                                if line.startswith("data: "):
                                    data_str = line[6:].strip()
                                    if data_str == "[DONE]":
                                        break
                                    yield data_str
                    finally:
                        await client.aclose()
                return stream_generator()
            else:
                # 非串流模式直接返回結果
                async with client:
                    response = await client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                    msg = data["choices"][0]["message"]
                    content = msg.get("content")
                    if not content:
                        content = msg.get("reasoning") or msg.get("reasoning_content") or ""
                    return content
        except Exception as e:
            logger.error(f"Failed to call vLLM chat_completion: {e}")
            raise e

    @classmethod
    async def query_rewrite(cls, query: str) -> str:
        """
        重寫查詢語句 (Query Rewriting) 以提高檢索準確度。
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一個搜尋檢索優化專家。請將使用者的查詢問題重寫為更適合向量搜尋（語意檢索）的關鍵詞或問題句。\n"
                    "規則：請只輸出重寫後的內容，不要有任何前導詞、說明、解釋或標點符號。"
                )
            },
            {"role": "user", "content": f"原始查詢：{query}"}
        ]
        try:
            rewritten = await cls.chat_completion(messages, temperature=0.3, max_tokens=256)
            return rewritten.strip()
        except Exception:
            return query

    @classmethod
    async def hyde_generation(cls, query: str) -> str:
        """
        生成假想文檔 (HyDE - Hypothetical Document Embeddings)。
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一個 RAG 系統的假設文檔生成器。\n"
                    "請針對使用者的問題，撰寫一段簡短、合理的「假設回答」或「相關知識文檔段落」。\n"
                    "此段落不需要保證事實完全正確，但必須具有高度的學術/技術相關詞彙，以便進行語意向量比對。\n"
                    "規則：長度控制在 150 字以內，只輸出段落內容，不要包含任何前置引言（例如『好的，以下是...』）或解釋。"
                )
            },
            {"role": "user", "content": f"問題：{query}"}
        ]
        try:
            hyde_doc = await cls.chat_completion(messages, temperature=0.7, max_tokens=512)
            return hyde_doc.strip()
        except Exception:
            return query
