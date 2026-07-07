import httpx
import logging
import asyncio
from typing import List
from config import settings

logger = logging.getLogger("airag.embedding")

class EmbeddingService:
    @staticmethod
    async def _fetch_embedding(text: str) -> List[float]:
        """
        依 EMBEDDING_API_STYLE 呼叫對應的本地 Embedding 服務端點（llama.cpp / Ollama / OpenAI 相容），
        並彈性解析多種可能的回傳格式後回傳向量。
        """
        base = settings.LLAMACPP_BASE_URL.rstrip('/')
        if settings.EMBEDDING_API_STYLE == "ollama":
            url = f"{base}/api/embeddings"
            payload = {"model": settings.EMBEDDING_MODEL, "prompt": text}
        elif settings.EMBEDDING_API_STYLE == "openai":
            url = f"{base}/v1/embeddings"
            payload = {"model": settings.EMBEDDING_MODEL, "input": text}
        else:  # "llamacpp"（預設，原生端點）
            url = f"{base}/embedding"
            payload = {"content": text}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload)
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
            logger.error(f"Failed to generate embedding via {settings.EMBEDDING_API_STYLE} ({url}): {e}")
            # 為利於測試，若 Embedding 服務尚未啟動，提供 4096 維度之模擬零向量作為降級防線
            logger.warning("Using a mock 4096-dim vector for testing bypass.")
            return [0.0] * 4096

    @staticmethod
    async def get_embedding(text: str) -> List[float]:
        """
        取得單一文本的向量。
        """
        return await EmbeddingService._fetch_embedding(text)

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
        取得語義密集向量（與 get_embedding 共用同一個 Embedding 服務端點）。
        """
        return await EmbeddingService._fetch_embedding(text)

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
    async def query_to_semantic_json(cls, question: str, filenames: list = None, tags: list = None, structured_metadata: list = None) -> dict:
        """
        將使用者的問題傳給 Instruct 語義化 AI，轉換成結構化 JSON 格式。
        """
        from datetime import datetime
        import json
        current_date = datetime.now().strftime("%Y-%m-%d")
        current_time_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        system_prompt = (
            "你是一個專門將用戶提問轉換為結構化語義檢索 JSON 的 AI 助手。請將用戶輸入的查詢（問題），轉換為如下的 JSON 格式：\n"
            "{\n"
            "  \"id\": \"query_YYYYMMDD_XXXX\",\n"
            "  \"text_content\": \"<原始用戶查詢>\",\n"
            "  \"embeddings_input\": \"<用於密集向量搜尋 (Dense Vector Search) 的優化重寫文字。長度控制在 100 字內。>\",\n"
            "  \"metadata\": {\n"
            "    \"source_file\": \"\",\n"
            "    \"page_number\": 1,\n"
            "    \"category\": \"<分析此查詢的分類類別，例如技術、一般等>\",\n"
            "    \"created_at\": \"<當前日期，格式 YYYY-MM-DD>\"\n"
            "  },\n"
            "  \"sparse_keywords\": [<用於關鍵字/稀疏檢索 (Sparse/Keyword Search) 的重要關鍵字、程式碼標誌、檔案名稱或實體名稱，數量 2-8 個>]\n"
            "}\n\n"
            "【嚴格核心規則】\n"
            "1. 檢索意圖區分：\n"
            "   - embeddings_input 是拿來餵給「向量資料庫搜尋」用的，而不是拿來直接回答用戶的！\n"
            "   - 搜尋用文字應該包含可能出現在知識庫原始文件或程式碼中的「核心特徵詞、函數名、欄位名」，必須去除虛胖客套話（如「請說明」、「請幫我解答」等）。\n"
            "2. 反幻想限制 (防腦補)：\n"
            "   - 只能基於使用者提問中明確提到的核心實體或關鍵字進行格式改寫與關鍵詞關聯拓展（例如補充常見副檔名或相近的檢索詞，如 p_zta 改寫為 p_zta.4gl）。\n"
            "   - 絕對不可自行推測、想像或加入使用者未提及的背景情境（例如：不要擅自猜測其屬於檔案管理、ERP 權限設定、或某個特定業務系統）。若不確定背景，請保持核心關鍵字與實體名稱即可！\n"
            "3. 輸出格式限制：請只輸出符合上述 Schema 的單一 JSON 字串，絕對不要包含 any Markdown 標記（如 ```json） or 任何額外的解釋性文字。\n"
            "4. 參考知識庫元資料對齊：如果提供有【參考知識庫結構地圖】或【參考知識庫元資料】，在提取 `sparse_keywords` 或進行 `embeddings_input` 優化時，應優先比對並使用清單中已存在的完整檔名（包含副檔名，如 `q_smy.4fd`、`q_smy.4gl`）。如果原始提問只有寫檔案主檔名（如 `q_smy`）且清單中存在包含副檔名的完整檔名，請在 `sparse_keywords` 中展開為完整檔名。\n"
            "5. 避免檢索詞語意稀釋 (防止通用無效詞污染)：\n"
            "   - 當查詢針對特定檔案、程式或資料庫欄位時，請不要將「什麼是」、「用途」、「意義」、「說明」、「功能」、「file extensions」、「meaning」、「purpose」、「usage」等通用語意詞語加入 embeddings_input 或 sparse_keywords 中。\n"
            "   - 因為原始程式碼或 XML 檔案內只會包含程式語法與結構，根本不會出現「意義」、「說明」等解釋性詞彙。加入這些通用詞會稀釋（Dilute）精確關鍵字的權重，導致無法正確檢索到該檔案。請保持 embeddings_input 與 sparse_keywords 的純淨度，僅保留精確的檔名、識別碼與程式特徵詞。\n"
            "   - 【例外】「圖片」、「圖表」、「截圖」、「照片」、「畫面」、「介面」等內容型態詞**不屬於**要剝除的通用客套詞，必須保留！因為知識庫中存在由圖片轉換而成的文字描述段落，這些詞正是命中該類段落的關鍵檢索訊號，剝除後會導致完全找不到圖片相關內容。\n\n"
            "【Few-Shot Examples (少樣本學習)】\n"
            "■ 範例 1 (程式檔案標籤)\n"
            "  - 輸入：說明 p_zta 標籤有哪些\n"
            "  - 良好輸出範例：\n"
            "    {\n"
            "      \"embeddings_input\": \"p_zta.4gl\",\n"
            "      \"sparse_keywords\": [\"p_zta.4gl\"]\n"
            "    }\n"
            "  - 錯誤輸出範例 (過度腦補背景與延伸問題，或加入多餘語意詞)：\n"
            "    {\n"
            "      \"embeddings_input\": \"說明 p_zta 的標籤屬性、設定步驟以及如何在系統權限管理中進行配置與疑難排解。\",\n"
            "      \"sparse_keywords\": [\"p_zta\", \"標籤\", \"權限管理\"]\n"
            "    } (錯誤原因：擅自想像了「設定步驟」、「權限管理」與「疑難排解」等使用者未提及的情境，且包含了「說明」、「標籤」等稀釋用詞)\n\n"
            "■ 範例 2 (資料庫欄位定義)\n"
            "  - 輸入：請說明gab_file的用途\n"
            "  - 良好輸出範例：\n"
            "    {\n"
            "      \"embeddings_input\": \"gab_file\",\n"
            "      \"sparse_keywords\": [\"gab_file\"]\n"
            "    }\n"
            "  - 錯誤輸出範例 (過度腦補背景)：\n"
            "    {\n"
            "      \"embeddings_input\": \"gab_file 的用途、格式、產生方式與備份復原方案，適用於企業 ERP 檔案管理系統。\",\n"
            "      \"sparse_keywords\": [\"gab_file\", \"用途\", \"備份復原\"]\n"
            "    } (錯誤原因：擅自腦補了「備份復原」、「企業 ERP」與「檔案管理系統」等技術情境)\n\n"
            "■ 範例 3 (程式呼叫與調用)\n"
            "  - 輸入：如何呼叫 q_smy\n"
            "  - 良好輸出範例：\n"
            "    {\n"
            "      \"embeddings_input\": \"q_smy.4gl call invoke run function\",\n"
            "      \"sparse_keywords\": [\"q_smy.4gl\", \"call\", \"invoke\"]\n"
            "    }\n"
            "  - 錯誤輸出範例 (過度腦補背景)：\n"
            "    {\n"
            "      \"embeddings_input\": \"在 Linux Docker 部署環境下呼叫 q_smy 的環境變數設定與 API 連線步驟。\",\n"
            "      \"sparse_keywords\": [\"q_smy\", \"呼叫\", \"Docker\"]\n"
            "    } (錯誤原因：擅自猜測是「Linux Docker」與「API 連線」等環境資訊)\n\n"
            "■ 範例 4 (一般文件 + 內容型態限定詞，例如圖片/圖表)\n"
            "  - 輸入：跟我說明 GP5.1建立備份營運中心.docx 圖片\n"
            "  - 良好輸出範例：\n"
            "    {\n"
            "      \"embeddings_input\": \"GP5.1建立備份營運中心.docx 圖片\",\n"
            "      \"sparse_keywords\": [\"GP5.1建立備份營運中心.docx\", \"圖片\"]\n"
            "    }\n"
            "  - 錯誤輸出範例 (把「圖片」也當成規則 5 的通用稀釋詞一併剝除)：\n"
            "    {\n"
            "      \"embeddings_input\": \"GP5.1建立備份營運中心.docx\",\n"
            "      \"sparse_keywords\": [\"GP5.1建立備份營運中心.docx\"]\n"
            "    } (錯誤原因：「圖片」是使用者明確提及的內容型態限定詞，不是「說明」這種客套語，剝除後會找不到該文件內由圖片轉換出來的描述段落)\n\n"
            f"當前日期為：{current_date}"
        )

        if structured_metadata:
            system_prompt += "\n\n【參考知識庫結構地圖】\n"
            for item in structured_metadata:
                fn = item.get("filename")
                c_list = item.get("class", [])
                t_list = item.get("tags", [])
                l_list = item.get("links_to", [])
                
                cls_val = ", ".join(c_list) if c_list else ""
                tags_val = ", ".join(t_list) if t_list else ""
                links_val = ", ".join(l_list) if l_list else ""
                
                system_prompt += f"- 檔案名稱：{fn}\n"
                if cls_val:
                    system_prompt += f"  * 類別：{cls_val}\n"
                if tags_val:
                    system_prompt += f"  * 標籤：{tags_val}\n"
                if links_val:
                    system_prompt += f"  * 關聯檔案/點位：{links_val}\n"
                system_prompt += "\n"
        elif filenames or tags:
            system_prompt += "\n\n【參考知識庫元資料】\n"
            if filenames:
                system_prompt += f"- 已存在的檔案名稱清單 (請優先在比對後將原始簡寫檔名，擴展重寫為這些已存在的完整名稱，並於 sparse_keywords 輸出完整名稱)：{json.dumps(filenames, ensure_ascii=False)}\n"
            if tags:
                system_prompt += f"- 已存在的標籤清單 (若用戶提及相關意圖，可在 category 與 sparse_keywords 中參考對齊使用)：{json.dumps(tags, ensure_ascii=False)}\n"
        
        url = f"{settings.DENSE_VECTOR_LLAMACPP_BASE_URL.rstrip('/')}/v1/chat/completions"
        base_payload = {
            "model": settings.DENSE_VECTOR_INSTRUCT_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"問題：{question}"}
            ],
            "max_tokens": 512,
            # 要求 llama.cpp 以 grammar-constrained decoding 強制輸出語法合法的 JSON，
            # 降低模型偶發漏逗號/多逗號等語法錯誤導致降級為 fallback 的機率。
            "response_format": {"type": "json_object"}
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
            "sparse_keywords": [question],
            "is_fallback": True
        }

        async def _call_and_parse(temperature: float) -> dict:
            payload = {**base_payload, "temperature": temperature}
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
                if "embeddings_input" not in parsed:
                    raise ValueError(f"JSON 缺少 embeddings_input 欄位: {parsed}")
                return parsed

        # 第 1 次維持低溫度以求穩定；重試時提高溫度打破確定性重複失敗
        # （實測觀察到同一問題於 temperature=0.1 下兩次重試會產生完全相同的語法錯誤，原地重試無效）
        retry_temperatures = [0.1, 0.5]
        max_attempts = len(retry_temperatures)
        for attempt, temperature in enumerate(retry_temperatures, start=1):
            try:
                parsed = await _call_and_parse(temperature)
                parsed["is_fallback"] = False
                if attempt > 1:
                    logger.info(f"Instruct AI JSON 於第 {attempt} 次嘗試後解析成功（temperature={temperature}）。")
                return parsed
            except Exception as e:
                if attempt < max_attempts:
                    logger.warning(f"Instruct AI JSON 轉換第 {attempt} 次嘗試失敗（temperature={temperature}），將以更高溫度重試: {e}")
                else:
                    logger.error(f"Instruct AI JSON 轉換重試 {max_attempts} 次後仍失敗，降級為 fallback: {e}")

        return fallback_json
