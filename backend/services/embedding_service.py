import httpx
import logging
import asyncio
from typing import List
from config import settings

logger = logging.getLogger("airag.embedding")

class EmbeddingService:
    @staticmethod
    async def get_embedding(text: str) -> List[float]:
        """
        向 llama.cpp (/embedding) 取得單一文本的向量。
        """
        url = f"{settings.LLAMACPP_BASE_URL.rstrip('/')}/embedding"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json={"content": text})
                response.raise_for_status()
                data = response.json()
                
                # 彈性解析多種可能的回傳格式
                # 1. 列表型格式 (e.g. [{'embedding': [...]}] 或是 [{'embedding': [[...]]}])
                if isinstance(data, list) and len(data) > 0:
                    first_item = data[0]
                    if isinstance(first_item, dict) and "embedding" in first_item:
                        emb = first_item["embedding"]
                        if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], list):
                            return emb[0]
                        return emb
                
                # 2. 字典型格式 (e.g. {'embedding': [...]} 或是 {'data': [{'embedding': [...]}]})
                if isinstance(data, dict):
                    if "embedding" in data:
                        emb = data["embedding"]
                        if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], list):
                            return emb[0]
                        return emb
                    if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
                        first_data = data["data"][0]
                        if isinstance(first_data, dict) and "embedding" in first_data:
                            emb = first_data["embedding"]
                            if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], list):
                                return emb[0]
                            return emb
                            
                raise ValueError(f"無法解析的向量回應格式: {data}")
        except Exception as e:
            logger.error(f"Failed to generate embedding via llama.cpp: {e}")
            # 為利於測試，若 llama.cpp 服務尚未啟動，提供 4096 維度之模擬零向量作為降級防線
            logger.warning("Using a mock 4096-dim vector for testing bypass.")
            return [0.0] * 4096

    @classmethod
    async def get_embeddings_batch(cls, texts: List[str]) -> List[List[float]]:
        """
        批次取得多個文本的向量（控制併發數量為 5）。
        """
        semaphore = asyncio.Semaphore(5)
        
        async def _embedded_task(text: str) -> List[float]:
            async with semaphore:
                return await cls.get_embedding(text)
        
        tasks = [_embedded_task(t) for t in texts]
        return await asyncio.gather(*tasks)

    @staticmethod
    async def get_semantic_embedding(text: str) -> List[float]:
        """
        向 LLAMACPP_BASE_URL (/embedding) 取得語義密集向量。
        """
        url = f"{settings.LLAMACPP_BASE_URL.rstrip('/')}/embedding"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json={"content": text})
                response.raise_for_status()
                data = response.json()
                
                # 彈性解析多種可能的回傳格式
                if isinstance(data, list) and len(data) > 0:
                    first_item = data[0]
                    if isinstance(first_item, dict) and "embedding" in first_item:
                        emb = first_item["embedding"]
                        if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], list):
                            return emb[0]
                        return emb
                
                if isinstance(data, dict):
                    if "embedding" in data:
                        emb = data["embedding"]
                        if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], list):
                            return emb[0]
                        return emb
                    if "data" in data and isinstance(data["data"], list) and len(data["data"]) > 0:
                        first_data = data["data"][0]
                        if isinstance(first_data, dict) and "embedding" in first_data:
                            emb = first_data["embedding"]
                            if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], list):
                                return emb[0]
                            return emb
                            
                raise ValueError(f"無法解析的向量回應格式: {data}")
        except Exception as e:
            logger.error(f"Failed to generate semantic embedding via llama.cpp (Instruct): {e}")
            # 為利於測試，若服務尚未啟動，提供 4096 維度之模擬零向量作為降級防線
            logger.warning("Using a mock 4096-dim vector for testing bypass.")
            return [0.0] * 4096

    @classmethod
    async def get_semantic_embeddings_batch(cls, texts: List[str]) -> List[List[float]]:
        """
        批次取得多個文本的語義向量（控制併發數量為 5）。
        """
        semaphore = asyncio.Semaphore(5)
        
        async def _embedded_task(text: str) -> List[float]:
            async with semaphore:
                return await cls.get_semantic_embedding(text)
        
        tasks = [_embedded_task(t) for t in texts]
        return await asyncio.gather(*tasks)

    @classmethod
    async def query_to_semantic_json(cls, question: str) -> dict:
        """
        將使用者的問題傳給 Instruct 語義化 AI，轉換成結構化 JSON 格式。
        """
        from datetime import datetime
        import json
        current_date = datetime.now().strftime("%Y-%m-%d")
        current_time_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        system_prompt = (
            "你是一個專門將用戶查詢轉換為語義化 JSON 的 AI 助手。\n"
            "請將用戶輸入的查詢（問題），轉換為如下的 JSON 格式：\n"
            "{\n"
            "  \"id\": \"query_YYYYMMDD_XXXX\",\n"
            "  \"text_content\": \"<原始用戶查詢>\",\n"
            "  \"embeddings_input\": \"<優化後的語義化向量輸入：請重寫或補充原始查詢，將其擴展為更適合語意密集檢索的描述，包含語句所描述的實體、目的與背景資訊。長度控制在 100 字內>\",\n"
            "  \"metadata\": {\n"
            "    \"source_file\": \"\",\n"
            "    \"page_number\": 1,\n"
            "    \"category\": \"<分析此查詢的分類類別，例如財務、安全、技術、一般等>\",\n"
            "    \"created_at\": \"<當前日期，格式 YYYY-MM-DD>\"\n"
            "  },\n"
            "  \"sparse_keywords\": [<從查詢中提取出的 3-8 個重要關鍵字或專有名詞>]\n"
            "}\n\n"
            "重要規則：請只輸出這個 JSON 內容，絕對不要包含任何 Markdown 標記（如 ```json）或任何額外的解釋性文字。\n"
            f"當前日期為：{current_date}"
        )
        
        url = f"{settings.DENSE_VECTOR_LLAMACPP_BASE_URL.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": settings.DENSE_VECTOR_INSTRUCT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"問題：{question}"}
            ],
            "temperature": 0.1,
            "max_tokens": 512
        }
        
        fallback_json = {
            "id": f"query_{current_time_id}",
            "text_content": question,
            "embeddings_input": question,
            "metadata": {
                "source_file": "",
                "page_number": 1,
                "category": "General",
                "created_at": current_date
            },
            "sparse_keywords": [question]
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                content = result["choices"][0]["message"]["content"].strip()
                
                # 簡單清理 Markdown 格式（如果有）
                if content.startswith("```"):
                    lines = content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()
                
                parsed = json.loads(content)
                # 確保必要欄位存在
                if "embeddings_input" in parsed:
                    return parsed
                return fallback_json
        except Exception as e:
            logger.error(f"Failed to convert query to semantic JSON: {e}")
            return fallback_json
