import httpx
import json
import logging
from typing import List, Dict, Any, AsyncGenerator
from config import settings

logger = logging.getLogger("airag.llm")

class LLMService:
    @staticmethod
    def _is_repeating_tail(accumulated: str, ngram_size: int = 25, trigger_count: int = 4) -> bool:
        """
        偵測累積文字尾端是否不斷重複同一段內容，用來判斷模型是否陷入無限迴圈。
        RAG 對話串流（routers/rag.py）與圖片描述生成（describe_image）共用同一套判斷邏輯。
        採用「連續週期性重複（Consecutive Loop）」演算法，避免非連續重複造成的誤判，
        並排除純標點符號與排版符號（如 Markdown 表格線、空格、換行）的干擾。
        """
        n = len(accumulated)
        min_period = 3
        # 週期上限設為 ngram_size * 10（預設 250）或總長度的一半，能完全涵蓋長技術名詞或上下文提示的長度
        max_period = max(250, ngram_size * 10)
        
        if n < min_period * trigger_count:
            return False
            
        for p in range(min_period, min(max_period + 1, n // trigger_count + 1)):
            suffix = accumulated[-p:]
            # 區塊內必須包含至少一個字母或數字（避免 Markdown 分隔線 |---| 或純換行空格觸發）
            if not any(c.isalnum() for c in suffix):
                continue
                
            is_loop = True
            for i in range(1, trigger_count):
                start = n - (i + 1) * p
                end = n - i * p
                if accumulated[start:end] != suffix:
                    is_loop = False
                    break
            if is_loop:
                return True
                
        return False

    @classmethod
    async def chat_completion(
        cls, 
        messages: List[Dict[str, Any]], 
        temperature: float = 0.7,
        max_tokens: int = 1024,
        repetition_penalty: float = None,
        frequency_penalty: float = None,
        stream: bool = False,
        return_finish_reason: bool = False,
        timeout: float = 60.0
    ) -> Any:
        """
        向 vLLM /chat/completions 發送請求。
        `timeout` 預設 60 秒；`max_tokens` 較大或請求內容複雜（例如多模態圖片描述）時，
        生成時間可能遠超過 60 秒，呼叫端應視情況傳入較長的 timeout，避免被誤判為連線失敗。
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
        # repetition_penalty / frequency_penalty 用於抑制地端模型重複輸出同一句話（無限迴圈）
        if repetition_penalty is not None:
            payload["repetition_penalty"] = repetition_penalty
        if frequency_penalty is not None:
            payload["frequency_penalty"] = frequency_penalty
        
        try:
            client = httpx.AsyncClient(timeout=timeout)
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
                    choice = data["choices"][0]
                    msg = choice["message"]
                    content = msg.get("content")
                    if not content:
                        content = msg.get("reasoning") or msg.get("reasoning_content") or ""
                    if return_finish_reason:
                        return content, choice.get("finish_reason")
                    return content
        except Exception as e:
            # httpx 的逾時例外（ReadTimeout/ConnectTimeout 等）字串化常常是空字串，
            # 只印 {e} 會讓 log 完全看不出真正原因，改印例外類別名稱 + repr 確保訊息不會是空的
            logger.error(f"Failed to call vLLM chat_completion: {type(e).__name__}: {e!r}")
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

    @classmethod
    async def describe_image(cls, image_bytes: bytes, mime_type: str, context_hint: str = "") -> tuple:
        """
        呼叫 vLLM 生成圖片的文字描述。改用串流消費，套用與 RAG 對話串流（routers/rag.py）相同的
        repetition_penalty/frequency_penalty 生成參數，並對思考(reasoning)內容與正式描述內容分別
        偵測是否陷入無限重複迴圈：
        - 思考階段偵測到重複（無限思考、遲遲未產生正式內容）：直接拋出例外，呼叫端依既有 caption_failed
          邏輯處理，不會誤把思考內容當作描述回傳。
        - 正式描述內容偵測到重複：中斷串流並回傳目前已累積的內容，truncated 標記為 True。
        回傳 (description, truncated)：truncated 為 True 代表 vLLM 因為 max_tokens 上限強制中斷輸出
        （常見於表格/BOM 等內容複雜的圖片）或偵測到重複而提前中斷，呼叫端不可當作完整描述處理。
        """
        import base64
        b64_str = base64.b64encode(image_bytes).decode("utf-8")

        messages = [
            {
                "role": "system",
                "content": (
                    "你是一個文件圖片內容描述助手。請詳細描述這張圖片的內容、類型"
                    "（例如：系統架構圖、流程圖、數據圖表、截圖、照片等）與其中可辨識的文字/數值，"
                    "供後續語意檢索使用。只輸出描述文字，不要有前導詞。"
                )
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"這張圖片位於文件段落：{context_hint}" if context_hint else "請描述這張圖片。"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_str}"}}
                ]
            }
        ]

        accumulated_content = ""
        accumulated_reasoning = ""
        finish_reason = None
        try:
            # 圖片內容複雜（文字/表格多）時，模型生成長度較大的描述可能需要遠超過一般文字對話的時間，
            # 這裡用較長的 timeout（5 分鐘），避免自架 vLLM 在生成大量 token 時被中途判定逾時失敗
            stream = await cls.chat_completion(
                messages, temperature=0.3, max_tokens=20480, timeout=300.0, stream=True,
                repetition_penalty=settings.DEFAULT_REPETITION_PENALTY,
                frequency_penalty=settings.DEFAULT_FREQUENCY_PENALTY
            )
            async for raw_chunk in stream:
                try:
                    chunk_data = json.loads(raw_chunk)
                except Exception:
                    continue
                choices = chunk_data.get("choices", [])
                if not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason"):
                    finish_reason = choice.get("finish_reason")
                delta = choice.get("delta", {})
                content_chunk = delta.get("content") or ""
                reasoning_chunk = delta.get("reasoning_content") or delta.get("thought") or delta.get("reasoning") or ""

                if reasoning_chunk:
                    accumulated_reasoning += reasoning_chunk
                    if cls._is_repeating_tail(accumulated_reasoning):
                        logger.warning(
                            f"Detected repeated reasoning loop while describing image, aborting early "
                            f"(context_hint={context_hint!r})"
                        )
                        raise RuntimeError("圖片描述生成偵測到無限思考迴圈，且尚未產生任何有效描述內容")

                if content_chunk:
                    accumulated_content += content_chunk
                    if cls._is_repeating_tail(accumulated_content):
                        logger.warning(
                            f"Detected repeated generation loop while describing image, aborting early "
                            f"(context_hint={context_hint!r})"
                        )
                        return accumulated_content.strip(), True
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Failed to generate description for image: {type(e).__name__}: {e!r}")
            raise e

        truncated = finish_reason == "length"
        if truncated:
            logger.warning(
                f"Image description was truncated by max_tokens (finish_reason=length), "
                f"content may be incomplete (context_hint={context_hint!r})"
            )
        return accumulated_content.strip(), truncated

