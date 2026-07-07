import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from beanie import PydanticObjectId

from models.knowledge_base import KnowledgeBase
from services.embedding_service import EmbeddingService
from services.qdrant_service import QdrantService
from services.llm_service import LLMService
from services.rerank_service import RerankService
from services.feedback_boost_service import FeedbackBoostService
from services.context_summarizer_service import ContextSummarizerService
from utils.token_counter import count_tokens
from utils.security import get_current_user
from config import settings

logger = logging.getLogger("airag.rag_router")
router = APIRouter(prefix="/rag", tags=["RAG"], dependencies=[Depends(get_current_user)])

class ChatHistoryItem(BaseModel):
    role: str
    content: str

class ChatParams(BaseModel):
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    repetition_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    top_k: Optional[int] = None
    score_threshold: Optional[float] = None
    filter_tags: Optional[List[str]] = None
    search_type: Optional[str] = "vector"
    context_summarize_trigger_tokens: Optional[int] = None
    read_attachment_content: Optional[bool] = False

class ChatRequest(BaseModel):
    question: str
    knowledge_base_id: Optional[str] = None
    chat_history: Optional[List[ChatHistoryItem]] = None
    params: Optional[ChatParams] = None
    # 語義資料庫查詢法 (search_type == "semantic_db_query") 專用：
    # 第一次請求不帶此欄位時，僅回傳候選查詢設定檔清單並暫停；
    # 使用者選定候選後，前端帶著此欄位重新呼叫，才會實際產生 SQL 並查詢資料庫。
    selected_db_profile_id: Optional[str] = None

def _get_attachment_effective_text(att) -> tuple:
    """
    語義混合附件查詢法：取得附件實際餵給 AI 的文字內容與來源說明。
    優先使用上傳時自動解析出的檔案實際內容（extracted_content）；
    僅在自動解析失敗或不支援該檔案格式時，才退回使用者填寫的備註（description）；
    兩者皆無則回報無可讀取內容，不假裝有內容可讀。
    """
    if att.extracted_content:
        return att.extracted_content, "自動擷取檔案實際內容"
    if att.description:
        note = f"（無法自動擷取此檔案格式的內容：{att.extraction_error}，改用使用者填寫的備註）" if att.extraction_error else "（使用者填寫的備註，未提供自動擷取內容）"
        return att.description, note
    return None, "（此附件無可讀取的內容：自動擷取失敗且未填寫備註）"

async def _run_semantic_db_query(request: "ChatRequest", question: str, result: dict):
    """
    語義資料庫查詢法的執行分支（不影響既有 vector/hybrid/semantic_hybrid* 查詢法的邏輯）：
    - 若未指定 knowledge_base_id（不限定知識庫）：掃描所有知識庫的查詢設定檔，找到候選後直接
      自動選擇分數最高者繼續執行，不中斷等待使用者選擇（沒有預設範圍可供人工判斷取捨）。
    - 若指定 knowledge_base_id 且請求未帶 selected_db_profile_id：執行第 1-2 步（語義理解 + Profile 比對），
      回傳候選清單事件並要求前端暫停等待使用者選擇。
    - 若已帶 selected_db_profile_id：執行第 3-5 步（SQL 產生、驗證、執行、結果整理），
      回傳 context_str/sources 供後續共用的主模型總結步驟繼續使用。
    這是一個 async generator，每個階段完成就立即 yield SSE 事件字串（而非累積到最後才一次回傳），
    確保等待較久的 LLM/資料庫呼叫期間，前端能即時看到對應步驟已切換為「執行中」動畫，而不是整段卡在 pending。
    由於 async generator 不能用帶值的 return，context_str/sources/should_stop 透過呼叫端傳入的
    可變 result dict 回傳（呼叫端在 `async for` 迭代完成後讀取 result 內容）。
    """
    from services.ai_db_query_service import AIDBQueryService, AIDBQueryError
    context_str = ""
    sources = []
    result["should_stop"] = True

    selected_profile_id = request.selected_db_profile_id
    global_scan = not bool(request.knowledge_base_id)

    # 已執行完成的設定檔查詢明細區塊。前端對同 key 的 step 事件是「覆蓋」而非累加，
    # 因此每次 success 事件都必須帶「到目前為止所有已執行設定檔」的完整彙整，
    # 否則執行多個設定檔時，後一個的內容會把前一個蓋掉，畫面上只剩最後一筆 SQL。
    executed_blocks = []

    async def _run_execute(profile_id: str, block_header: str = "", prefix_note: str = ""):
        # 累加而非覆寫 context_str/sources，讓「不限定知識庫」模式可依序執行多個設定檔並合併結果
        nonlocal context_str
        running_line = (
            f"{block_header} 正在產生 SQL 並查詢資料庫..."
            if block_header else "已選定查詢設定檔，正在產生 SQL 並查詢資料庫..."
        )
        if prefix_note:
            running_line = f"{prefix_note}\n{running_line}"
        running_content = "\n\n".join(executed_blocks + [running_line]) if executed_blocks else running_line
        yield f"event: step\ndata: {json.dumps({'step': 'vector_search', 'status': 'running', 'content': running_content}, ensure_ascii=False)}\n\n"

        exec_result = await AIDBQueryService.execute(question=question, profile_id=profile_id)
        piece = exec_result["context_text"]
        context_str = f"{context_str}\n\n{piece}" if context_str else piece
        sources.append({
            "chunk_id": exec_result["profile_id"],
            "content": piece,
            "metadata": {
                "filename": f"DB_QUERY_PROFILE_{exec_result['profile_name']}",
                "generated_sql": exec_result["generated_sql"]
            },
            "score": 1.0,
            "token_count": count_tokens(piece)
        })
        header = block_header or f"已選定設定檔：{exec_result['profile_name']}"
        block = (
            f"{header}\n"
            f"產生的 SQL：\n```sql\n{exec_result['generated_sql']}\n```\n"
            f"查得 {exec_result['row_count']} 筆資料，耗時 {exec_result['elapsed_ms']}ms"
        )
        executed_blocks.append(block)
        success_content = "\n\n".join(executed_blocks)
        yield f"event: step\ndata: {json.dumps({'step': 'vector_search', 'status': 'success', 'content': success_content}, ensure_ascii=False)}\n\n"

    try:
        if not selected_profile_id:
            # 第 1 步：語義理解 —— 先完整跑完並明確標記 success，再進入第 2 步，避免前端誤以為兩步同時在跑
            analysis_running = f'正在取得目前所有查詢設定檔清單，交給地端 AI 判斷需要用到哪幾個...\n原始提問："{question}"'
            yield f"event: step\ndata: {json.dumps({'step': 'semantic_analysis', 'status': 'running', 'content': analysis_running}, ensure_ascii=False)}\n\n"

            match_result = await AIDBQueryService.match_profiles(question=question, knowledge_base_id=request.knowledge_base_id)
            candidates = match_result["candidates"]
            selection_reason = match_result["selection_reason"]

            analysis_json = {
                "original_question": question,
                "scope": "所有知識庫（不限定）" if global_scan else "指定知識庫",
                "selected_profiles": [c["name"] for c in candidates],
                "selection_reason": selection_reason
            }
            json_str = json.dumps(analysis_json, indent=2, ensure_ascii=False)
            analysis_success = (
                f"【地端 AI 語義分析結果】\n"
                f"結構化 JSON：\n```json\n{json_str}\n```"
            )
            yield f"event: step\ndata: {json.dumps({'step': 'semantic_analysis', 'status': 'success', 'content': analysis_success}, ensure_ascii=False)}\n\n"

            # 第 2 步：Profile 選擇結果彙整 —— 待第 1 步完全結束後才開始
            yield f"event: step\ndata: {json.dumps({'step': 'vector_search', 'status': 'running', 'content': '正在依語義判斷結果彙整候選查詢設定檔...'}, ensure_ascii=False)}\n\n"

            if not candidates:
                yield f"event: step\ndata: {json.dumps({'step': 'vector_search', 'status': 'failed', 'content': '查無對應的資料庫查詢設定檔，請先於「資料庫匯入向量化」頁面建立查詢設定檔。'}, ensure_ascii=False)}\n\n"
                yield f"event: chunk\ndata: {json.dumps({'type': 'content', 'content': '很抱歉，找不到符合此問題的資料庫查詢設定檔。'}, ensure_ascii=False)}\n\n"
                yield f"event: sources\ndata: {json.dumps({'sources': []}, ensure_ascii=False)}\n\n"
                yield f"event: chunk\ndata: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                return

            candidate_lines = "\n".join(
                f"[{i + 1}] {c['name']}（表格: {c['table_name']}, Score: {c['score']:.4f}）"
                for i, c in enumerate(candidates)
            )
            vector_search_success_content = f"找到 {len(candidates)} 個候選查詢設定檔：\n{candidate_lines}"
            yield f"event: step\ndata: {json.dumps({'step': 'vector_search', 'status': 'success', 'content': vector_search_success_content}, ensure_ascii=False)}\n\n"

            if global_scan:
                # 不限定知識庫時，沒有預設範圍可供使用者判斷取捨；問題可能同時橫跨多個表格/設定檔
                # （例如同時問到「附件」與「文章」），因此依序執行 AI 選出的前 N 個候選並合併結果，
                # 而非只取單一設定檔，避免漏答問題中涉及的其他表格。
                selected_profiles = candidates[:settings.AI_DB_QUERY_MAX_PROFILES_PER_QUERY]
                total = len(selected_profiles)
                if total == 1:
                    auto_note = f"未指定知識庫，AI 已自動選擇設定檔：{selected_profiles[0]['name']}（自動選取，非人工確認）"
                else:
                    selected_names = "、".join(c["name"] for c in selected_profiles)
                    auto_note = (
                        f"未指定知識庫，AI 已自動選擇 {total} 個相關設定檔：{selected_names}"
                        f"（自動選取，非人工確認，將分別查詢後合併結果）"
                    )
                for idx, candidate in enumerate(selected_profiles):
                    block_header = f"【設定檔 {idx + 1}/{total}：{candidate['name']}】" if total > 1 else ""
                    async for evt in _run_execute(
                        candidate["profile_id"],
                        block_header=block_header,
                        prefix_note=auto_note if idx == 0 else ""
                    ):
                        yield evt
                result["context_str"] = context_str
                result["sources"] = sources
                result["should_stop"] = False
                return

            yield f"event: step\ndata: {json.dumps({'step': 'profile_candidates', 'status': 'success', 'content': '請選擇其中一個候選查詢設定檔以繼續查詢：', 'candidates': candidates}, ensure_ascii=False)}\n\n"
            yield f"event: chunk\ndata: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            return

        # 第 3-5 步：使用者已選定候選設定檔（指定知識庫時的兩段式流程），
        # semantic_analysis 已於第一次請求中標記 success，這裡只需接續 vector_search
        async for evt in _run_execute(selected_profile_id):
            yield evt
        result["context_str"] = context_str
        result["sources"] = sources
        result["should_stop"] = False
    except AIDBQueryError as e:
        yield f"event: step\ndata: {json.dumps({'step': 'vector_search', 'status': 'failed', 'content': str(e)}, ensure_ascii=False)}\n\n"
        yield f"event: chunk\ndata: {json.dumps({'type': 'content', 'content': f'查詢失敗：{str(e)}'}, ensure_ascii=False)}\n\n"
        yield f"event: sources\ndata: {json.dumps({'sources': []}, ensure_ascii=False)}\n\n"
        yield f"event: chunk\ndata: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

async def rag_chat_stream(request: ChatRequest):
    question = request.question
    
    # Extract params with fallbacks
    temperature = 0.3
    top_k = 13
    score_threshold = 0.65
    max_tokens = 1024
    repetition_penalty = settings.DEFAULT_REPETITION_PENALTY
    frequency_penalty = settings.DEFAULT_FREQUENCY_PENALTY
    filter_tags = None
    search_type = "vector"
    context_summarize_trigger_tokens = settings.DEFAULT_CONTEXT_SUMMARIZE_THRESHOLD_TOKENS
    read_attachment_content = False

    if request.params:
        if request.params.temperature is not None:
            temperature = request.params.temperature
        if request.params.top_k is not None:
            top_k = request.params.top_k
        if request.params.score_threshold is not None:
            score_threshold = request.params.score_threshold
        if request.params.max_tokens is not None:
            max_tokens = request.params.max_tokens
        if request.params.repetition_penalty is not None:
            repetition_penalty = request.params.repetition_penalty
        if request.params.frequency_penalty is not None:
            frequency_penalty = request.params.frequency_penalty
        if request.params.filter_tags is not None:
            filter_tags = request.params.filter_tags
        if request.params.search_type is not None:
            search_type = request.params.search_type
        if request.params.context_summarize_trigger_tokens is not None:
            context_summarize_trigger_tokens = request.params.context_summarize_trigger_tokens
        if request.params.read_attachment_content is not None:
            read_attachment_content = request.params.read_attachment_content

    sources = []
    attachments_to_send = []
    attachments_data = []
    context_str = ""
    context_summary = {
        "total_tokens": 0,
        "batch_count": 0,
        "rounds": 0,
        "was_summarized": False,
        "threshold_tokens": context_summarize_trigger_tokens
    }

    # 1. 如果有指定知識庫，執行向量檢索獲取 Context
    if search_type == "semantic_db_query":
        db_query_result = {}
        async for evt in _run_semantic_db_query(request, question, db_query_result):
            yield evt
        context_str = db_query_result.get("context_str", "")
        sources = db_query_result.get("sources", [])
        if db_query_result.get("should_stop", True):
            return
    elif request.knowledge_base_id:
        try:
            kb_id = PydanticObjectId(request.knowledge_base_id)
            kb = await KnowledgeBase.get(kb_id)
            if kb:
                try:
                    # 發送「語義分析」進行中事件
                    step_data = {
                        "step": "semantic_analysis",
                        "status": "running",
                        "content": f"開始將問題轉換為嵌入向量...\n原始提問：\"{question}\""
                    }
                    yield f"event: step\ndata: {json.dumps(step_data, ensure_ascii=False)}\n\n"
                    
                    # 取得提問向量
                    if search_type in ("semantic_hybrid", "semantic_hybrid_feedback", "semantic_hybrid_attachment"):
                        # 先發送進行中事件表示在進行 Instruct 語義分析
                        step_data = {
                            "step": "semantic_analysis",
                            "status": "running",
                            "content": f"正在發送提問至地端 AI ({settings.DENSE_VECTOR_INSTRUCT_MODEL}) 進行語義分析與結構化轉換...\n原始提問：\"{question}\""
                        }
                        yield f"event: step\ndata: {json.dumps(step_data, ensure_ascii=False)}\n\n"
                        
                        # 取得該知識庫的 metadata
                        metadata_info = await QdrantService.get_unique_metadata(kb.qdrant_collection_name)
                        filenames = metadata_info.get("filenames", [])
                        tags = metadata_info.get("tags", [])
                        structured_metadata = metadata_info.get("structured_metadata", [])
                        logger.info(
                            f"[RAG] 已從 Qdrant 取得結構化元資料 - 檔案數: {len(filenames)}, 標籤數: {len(tags)}, 結構化項目數: {len(structured_metadata)}, 檔名樣例: {filenames[:5]}, 標籤: {tags}"
                        )
                        
                        # 呼叫 Instruct AI 轉 JSON
                        semantic_json = await EmbeddingService.query_to_semantic_json(
                            question, filenames=filenames, tags=tags, structured_metadata=structured_metadata
                        )
                        logger.info(f"[RAG] 已從 Instruct AI 取得結構化 JSON，以下是結構化內容: {semantic_json}")

                        embeddings_input = semantic_json.get("embeddings_input", question)
                        sparse_keywords = semantic_json.get("sparse_keywords", [])
                        
                        # 顯示結構化 JSON
                        json_str = json.dumps(semantic_json, indent=2, ensure_ascii=False)
                        step_data = {
                            "step": "semantic_analysis",
                            "status": "running",
                            "content": (
                                f"【地端 AI 語義分析結果】\n"
                                f"結構化 JSON：\n"
                                f"```json\n{json_str}\n```\n"
                                f"正在產生密集向量（輸入：\"{embeddings_input}\"，模型：{settings.EMBEDDING_MODEL}）..."
                            )
                        }
                        yield f"event: step\ndata: {json.dumps(step_data, ensure_ascii=False)}\n\n"
                        
                        # 轉換 embeddings_input 為密集向量
                        query_vector = await EmbeddingService.get_semantic_embedding(embeddings_input)
                        vector_preview = str(query_vector[:10]) + "..."
                        
                        step_data = {
                            "step": "semantic_analysis",
                            "status": "success",
                            "content": (
                                f"【地端 AI 語義密集嵌入】\n"
                                f"結構化 JSON：\n"
                                f"```json\n{json_str}\n```\n"
                                f"密集向量模型: {settings.EMBEDDING_MODEL}\n"
                                f"Base URL: {settings.LLAMACPP_BASE_URL}\n"
                                f"向量維度: {len(query_vector)}\n"
                                f"部分向量: {vector_preview}"
                            )
                        }
                        yield f"event: step\ndata: {json.dumps(step_data, ensure_ascii=False)}\n\n"
                        
                        # 設定用來做稀疏查詢的文本
                        search_query_text = " ".join(sparse_keywords) if sparse_keywords else question
                    else:
                        query_vector = await EmbeddingService.get_embedding(question)
                        vector_preview = str(query_vector[:10]) + "..."
                        step_data = {
                            "step": "semantic_analysis",
                            "status": "success",
                            "content": (
                                f"【標準語義密集嵌入】\n"
                                f"Base URL: {settings.LLAMACPP_BASE_URL}\n"
                                f"向量維度: {len(query_vector)}\n"
                                f"部分向量: {vector_preview}"
                            )
                        }
                        yield f"event: step\ndata: {json.dumps(step_data, ensure_ascii=False)}\n\n"
                        
                        search_query_text = question
                    
                    # 發送「向量資料查詢」進行中事件
                    step_data = {
                        "step": "vector_search",
                        "status": "running",
                        "content": f"正在進行資料庫檢索...\n檢索模式: {search_type}\nTop-K: {top_k}\n最低相似度閾值: {score_threshold}"
                    }
                    yield f"event: step\ndata: {json.dumps(step_data, ensure_ascii=False)}\n\n"

                    # Qdrant 相似度與雙路融合檢索
                    feedback_boost_applied = False
                    if search_type in ("semantic_hybrid", "semantic_hybrid_feedback", "semantic_hybrid_attachment"):
                        raw_results = await QdrantService.search_similar_two_step(
                            collection_name=kb.qdrant_collection_name,
                            query_vector=query_vector,
                            query_text=search_query_text,
                            search_type="semantic_hybrid",
                            top_k=top_k,
                            score_threshold=score_threshold,
                            filter_tags=filter_tags,
                            sparse_keywords=sparse_keywords
                        )
                        # 借用 Instruct LLM 對融合後的候選片段做相關性重排序，取前 top_k 筆
                        if raw_results:
                            raw_results = await RerankService.rerank(question, raw_results, top_k)
                        # 語義混合回饋查詢法：依歷史人工回饋對命中片段做分數加權重排
                        if search_type == "semantic_hybrid_feedback" and raw_results:
                            raw_results = await FeedbackBoostService.apply_feedback_boost(
                                raw_results, knowledge_base_id=request.knowledge_base_id
                            )
                            feedback_boost_applied = True

                        # 語義混合附件查詢法：收集並查詢關聯附件
                        if search_type == "semantic_hybrid_attachment" and raw_results:
                            attachment_ids = []
                            for item in raw_results:
                                meta = item.get("metadata", {})
                                linked_atts = meta.get("linked_attachments") or []
                                for aid in linked_atts:
                                    if aid and aid not in attachment_ids:
                                        attachment_ids.append(aid)

                            from models.attachment import Attachment
                            for aid in attachment_ids:
                                try:
                                    att = await Attachment.get(PydanticObjectId(aid))
                                    if att:
                                        attachments_data.append(att)
                                        attachments_to_send.append({
                                            "id": str(att.id),
                                            "original_filename": att.original_filename,
                                            "description": att.description,
                                            "download_url": f"/api/attachments/{att.id}/download"
                                        })
                                except Exception as att_err:
                                    logger.warning(f"Failed to fetch attachment {aid}: {att_err}")
                    else:
                        raw_results = await QdrantService.search_similar(
                            collection_name=kb.qdrant_collection_name,
                            query_vector=query_vector,
                            query_text=search_query_text,
                            search_type=search_type,
                            top_k=top_k,
                            score_threshold=score_threshold,
                            filter_tags=filter_tags
                        )
                    
                    # 整理 Chunks 為 Context
                    context_parts = []
                    retrieved_summary = []
                    # 同段落可能有多張圖片，parent_id 去重時只有一筆會留在 raw_results，其餘會附掛在
                    # 該筆結果的 metadata.image_chunks 中（原本只用來給前端顯示縮圖清單）。這裡用同一個
                    # 集合追蹤已經送進 context 的 image_filename，避免同張圖片因為被多筆結果引用而重複塞入。
                    seen_image_filenames = set()
                    for idx, item in enumerate(raw_results):
                        meta = item.get("metadata", {})
                        sources.append({
                            "chunk_id": item.get("chunk_id"),
                            "content": item.get("content", ""),
                            "metadata": {
                                "filename": meta.get("filename"),
                                "page": meta.get("page"),
                                "section": meta.get("section"),
                                "chunk_index": meta.get("chunk_index"),
                                "tags": meta.get("tags", []),
                                "class": meta.get("class", []),
                                "links_to": meta.get("links_to", []),
                                "linked_attachments": meta.get("linked_attachments", []),
                                "chunk_type": meta.get("chunk_type"),
                                "image_filename": meta.get("image_filename"),
                                "image_chunks": meta.get("image_chunks", [])
                            },
                            "score": item.get("score", 0.0),
                            "token_count": count_tokens(item.get("content", ""))
                        })
                        chunk_idx = meta.get("chunk_index")
                        chunk_idx_str = f"#{chunk_idx}" if chunk_idx is not None else "?"
                        context_parts.append(f"【來源文件：{meta.get('filename', '未知')} | 段落編號：{chunk_idx_str}】\n內容：{item.get('content', '')}")
                        if meta.get("chunk_type") == "image" and meta.get("image_filename"):
                            seen_image_filenames.add(meta.get("image_filename"))

                        # 攤平同段落的其他圖片描述併入 context，否則這些圖片只會出現在前端縮圖清單，
                        # 從未真正送進 LLM 的 context，導致 AI 只看得到 parent_id 去重後倖存的那一張圖
                        for img_chunk in meta.get("image_chunks", []):
                            img_filename = img_chunk.get("metadata", {}).get("image_filename")
                            if not img_filename or img_filename in seen_image_filenames:
                                continue
                            seen_image_filenames.add(img_filename)
                            img_meta = img_chunk.get("metadata", {})
                            img_chunk_idx = img_meta.get("chunk_index")
                            img_chunk_idx_str = f"#{img_chunk_idx}" if img_chunk_idx is not None else "?"
                            context_parts.append(
                                f"【來源文件：{img_meta.get('filename') or meta.get('filename', '未知')} | 段落編號：{img_chunk_idx_str}（圖片描述）】\n"
                                f"內容：{img_chunk.get('content', '')}"
                            )

                        score_label = "RRF Score" if search_type in ["hybrid", "semantic_hybrid", "semantic_hybrid_feedback", "semantic_hybrid_attachment"] else "Score"
                        retrieved_summary.append(f"[{idx+1}] 來源文件：{meta.get('filename', '未知')} | P.{meta.get('page', '?')} | {score_label}: {item.get('score', 0.0):.4f}\\n內容預覽：{item.get('content', '')[:100]}...")

                    if context_parts:
                        context_str = "\n---\n".join(context_parts)
                        search_details = f"檢索模式: {search_type}\\n Collection: {kb.qdrant_collection_name}\\n成功召回 {len(raw_results)} 筆相關段落：\\n\\n" + "\\n\\n".join(retrieved_summary)
                        if feedback_boost_applied:
                            search_details += "\\n\\n【已套用歷史回饋加權】依人工標註正確/不正確次數對命中片段分數進行了重排。"
                    else:
                        search_details = "向量檢索完成。沒有找到符合相似度閥值限制的相關資料。"
                    
                    yield f"event: step\ndata: {json.dumps({'step': 'vector_search', 'status': 'success', 'content': search_details}, ensure_ascii=False)}\n\n"

                    # 語義混合附件查詢法：若勾選「AI 讀取附件內容」且確實找到關聯附件，
                    # 送出獨立的擷取步驟讓使用者親眼確認 AI 實際讀到了哪些附件、讀到什麼實際內容
                    # （優先使用上傳時自動解析出的檔案實際內容，而非使用者填寫的備註，見 _get_attachment_effective_text）
                    if search_type == "semantic_hybrid_attachment" and read_attachment_content and attachments_data:
                        extraction_running = f"正在讀取 {len(attachments_data)} 個關聯附件的實際內容..."
                        yield f"event: step\ndata: {json.dumps({'step': 'attachment_extraction', 'status': 'running', 'content': extraction_running, 'label': '擷取附件內容'}, ensure_ascii=False)}\n\n"

                        extraction_parts = []
                        for idx, att in enumerate(attachments_data):
                            att_text, source_note = _get_attachment_effective_text(att)
                            att_token_count = count_tokens(att_text or "")
                            display_text = att_text if att_text else "（無可讀取的內容）"
                            extraction_parts.append(
                                f"[{idx+1}] {att.original_filename}（Tokens: {att_token_count}）{source_note}\n內容：\n{display_text}"
                            )
                        extraction_success = f"已讀取 {len(attachments_data)} 個關聯附件的實際內容：\n\n" + "\n\n".join(extraction_parts)
                        yield f"event: step\ndata: {json.dumps({'step': 'attachment_extraction', 'status': 'success', 'content': extraction_success, 'label': '擷取附件內容'}, ensure_ascii=False)}\n\n"

                except Exception as inner_e:
                    logger.error(f"Failed to perform vector search or embedding for RAG: {inner_e}")
                    yield f"event: step\ndata: {json.dumps({'step': 'vector_search', 'status': 'failed', 'content': f'向量資料查詢錯誤: {str(inner_e)}'}, ensure_ascii=False)}\n\n"
            else:
                logger.warning(f"Knowledge base with ID {kb_id} not found.")
                yield f"event: step\ndata: {json.dumps({'step': 'vector_search', 'status': 'failed', 'content': f'找不到指定的知識庫 ID: {kb_id}'}, ensure_ascii=False)}\n\n"
        except Exception as outer_e:
            logger.error(f"Invalid knowledge_base_id format or error loading KB: {outer_e}")
            yield f"event: step\ndata: {json.dumps({'step': 'vector_search', 'status': 'failed', 'content': f'知識庫 ID 格式錯誤或載入失敗: {str(outer_e)}'}, ensure_ascii=False)}\n\n"
    else:
        yield f"event: step\ndata: {json.dumps({'step': 'semantic_analysis', 'status': 'success', 'content': '無目標知識庫，略過語義分析。'}, ensure_ascii=False)}\n\n"
        yield f"event: step\ndata: {json.dumps({'step': 'vector_search', 'status': 'success', 'content': '無目標知識庫，略過向量資料查詢。'}, ensure_ascii=False)}\n\n"

    # 1.5. 如果需要，對檢索出的上下文進行 Map-Reduce 分批摘要
    if context_str:
        att_tokens = 0
        if search_type == "semantic_hybrid_attachment" and read_attachment_content:
            for att in attachments_data:
                att_text, _ = _get_attachment_effective_text(att)
                att_tokens += count_tokens(att_text or "")
        context_summary["total_tokens"] = sum(s.get("token_count", 0) for s in sources) + att_tokens

        blocks = []
        is_db = (search_type == "semantic_db_query")
        if is_db:
            for idx, src in enumerate(sources):
                blocks.append({
                    "text": src["content"],
                    "label": src["metadata"].get("filename", f"DB_QUERY_{idx}")
                })
        else:
            for src in sources:
                meta = src.get("metadata", {})
                chunk_idx = meta.get("chunk_index")
                chunk_idx_str = f"#{chunk_idx}" if chunk_idx is not None else "?"
                text = f"【來源文件：{meta.get('filename', '未知')} | 段落編號：{chunk_idx_str}】\n內容：{src.get('content', '')}"
                label = f"{meta.get('filename', '未知')} {chunk_idx_str}"
                blocks.append({"text": text, "label": label})
            
            # 語義混合附件查詢法：若啟用讀取附件內容，將附件的實際內容（優先自動擷取，見 _get_attachment_effective_text）作為額外區塊加入
            if search_type == "semantic_hybrid_attachment" and read_attachment_content:
                for att in attachments_data:
                    att_text, _ = _get_attachment_effective_text(att)
                    text = f"【關聯附件：{att.original_filename} | 實際內容】\n{att_text or '無可讀取的內容'}"
                    label = f"附件: {att.original_filename}"
                    blocks.append({"text": text, "label": label})

        if blocks:
            summarize_result = {}
            try:
                async for evt in ContextSummarizerService.maybe_summarize(
                    question=question,
                    blocks=blocks,
                    threshold_tokens=context_summarize_trigger_tokens,
                    result=summarize_result,
                    is_db=is_db
                ):
                    yield evt
                if "context_str" in summarize_result:
                    context_str = summarize_result["context_str"]
                context_summary["batch_count"] = summarize_result.get("batch_count", 0)
                context_summary["rounds"] = summarize_result.get("rounds", 0)
                context_summary["was_summarized"] = summarize_result.get("was_summarized", False)
            except Exception as summarize_e:
                logger.error(f"Context summarization failed, falling back to original unsummarized context: {summarize_e}")
                yield f"event: step\ndata: {json.dumps({'step': 'context_summarize_error', 'status': 'failed', 'content': f'分批摘要失敗，將改用原始未摘要內容繼續回答：{str(summarize_e)}'}, ensure_ascii=False)}\n\n"

    # 發送模型推理思考步驟事件
    yield f"event: step\ndata: {json.dumps({'step': 'llm_thinking', 'status': 'running', 'content': '正在整理思緒...'}, ensure_ascii=False)}\n\n"
    yield f"event: step\ndata: {json.dumps({'step': 'conclusion', 'status': 'pending', 'content': ''}, ensure_ascii=False)}\n\n"

    # 2. 構建 System Prompt 與 Messages
    if search_type == "semantic_db_query" and context_str:
        # 語義資料庫查詢法專用總結 Prompt：內容是資料庫查詢結果（非文件段落），不需要段落引用格式，
        # 避免既有文件引用格式的規則誤導模型過度保守地判定「查無相關資訊」。
        system_prompt = (
            "你是一個專業的資料庫問答助理。以下「資料庫查詢結果」是依照使用者問題實際從資料庫執行 SQL 查詢後取得的真實資料，"
            "請直接根據這些資料回答使用者的問題。\n"
            "規則：\n"
            "1. 只要查詢結果中有任何一筆資料合理對應使用者問題描述的對象（即使欄位用詞與使用者問法不完全一致），就應該根據該筆資料直接回答，不要因為用詞不完全相同就判定無關。\n"
            "2. 只有在查詢結果完全是空的、或所有資料列明顯都與問題無關時，才回答『知識庫沒有相關資訊。』，不要編造查詢結果中沒有的內容。\n"
            "3. 保持回答清晰、專業且符合邏輯，可視需要簡述用了哪張表格或欄位得出結論。\n\n"
            f"【資料庫查詢結果】\n{context_str}"
        )
    elif context_str:
        system_prompt = (
            "你是一個專業的 RAG 智慧對話助理。請根據以下提供的「參考資料」回答使用者的問題。\n"
            "規則：\n"
            "1. 儘量使用參考資料中的資訊來回答。\n"
            "2. 如果參考資料不足以回答問題，請直接回答『知識庫沒有相關資訊。』，絕對不要使用你的既有知識回答，也不要編造任何內容。\n"
            "3. 保持回答清晰、專業且符合邏輯。\n"
            "4. 回答時，必須明確在回答的開頭或結尾指出你是參考了哪些文檔引用段落，格式範例：\n"
            "   「依據 [文件名] 段落: #段落編號 做出以下結論：」或是「（參考來源：[文件名] 段落: #段落編號）」\n"
            "   若是引用多個段落，請使用頓號（、）或逗號分隔，例如：「依據[知識庫操作說明.md] 段落: #43、[知識庫操作說明.md] 段落: #45、[知識庫操作說明.md] 段落: #10 做出以下結論：」\n\n"
            f"【參考資料】\n{context_str}"
        )
    else:
        system_prompt = (
            "你是一個專業的 RAG 智慧對話助理。由於目前沒有提供任何參考資料，請直接回答『知識庫沒有相關資訊。』，絕對不要回答其他內容。"
        )

    messages = [{"role": "system", "content": system_prompt}]
    
    # 加入歷史對話
    if request.chat_history:
        for msg in request.chat_history:
            messages.append({"role": msg.role, "content": msg.content})
            
    # 加入目前的提問
    messages.append({"role": "user", "content": question})

    # 3. 呼叫 vLLM 並串流輸出
    try:
        vllm_stream = await LLMService.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            repetition_penalty=repetition_penalty,
            frequency_penalty=frequency_penalty,
            stream=True
        )

        # 重複輸出偵測：即使 repetition_penalty 未能完全避免，也要能主動中斷無限迴圈
        # （判斷邏輯與 LLMService.describe_image() 共用同一個 _is_repeating_tail()）
        accumulated_content = ""

        async for raw_chunk in vllm_stream:
            try:
                chunk_data = json.loads(raw_chunk)
                choices = chunk_data.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content_chunk = delta.get("content") or ""
                    reasoning_chunk = delta.get("reasoning_content") or delta.get("thought") or delta.get("reasoning") or ""
                    if reasoning_chunk:
                        yield f"event: chunk\ndata: {json.dumps({'type': 'reasoning', 'content': reasoning_chunk}, ensure_ascii=False)}\n\n"
                    if content_chunk:
                        yield f"event: chunk\ndata: {json.dumps({'type': 'content', 'content': content_chunk}, ensure_ascii=False)}\n\n"

                        accumulated_content += content_chunk
                        if LLMService._is_repeating_tail(accumulated_content):
                            logger.warning("Detected repeated generation loop, aborting stream early.")
                            warning_msg = "\n\n[系統提示] 偵測到模型重複輸出相同內容，已自動中斷生成。"
                            yield f"event: chunk\ndata: {json.dumps({'type': 'content', 'content': warning_msg}, ensure_ascii=False)}\n\n"
                            break
            except Exception as parse_e:
                logger.error(f"Error parsing SSE chunk: {raw_chunk}, error: {parse_e}")
    except Exception as llm_e:
        logger.error(f"Failed to stream from vLLM: {llm_e}")
        error_msg = f"[系統連線錯誤] 無法從 vLLM 服務取得回覆：{str(llm_e)}"
        yield f"event: chunk\ndata: {json.dumps({'type': 'content', 'content': error_msg}, ensure_ascii=False)}\n\n"

    # 4. 傳送 sources 事件與 done 事件給前端
    yield f"event: sources\ndata: {json.dumps({'sources': sources, 'context_summary': context_summary, 'attachments': attachments_to_send}, ensure_ascii=False)}\n\n"
    yield f"event: chunk\ndata: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

@router.post("/chat")
async def chat_stub(request: ChatRequest):
    return StreamingResponse(rag_chat_stream(request), media_type="text/event-stream")

@router.get("/history")
async def history_stub():
    return {"total": 0, "items": []}

@router.delete("/history/{session_id}")
async def delete_history_stub(session_id: str):
    return {"message": "刪除成功"}
