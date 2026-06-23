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
from utils.security import get_current_user

logger = logging.getLogger("airag.rag_router")
router = APIRouter(prefix="/rag", tags=["RAG"], dependencies=[Depends(get_current_user)])

class ChatHistoryItem(BaseModel):
    role: str
    content: str

class ChatParams(BaseModel):
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_k: Optional[int] = None
    score_threshold: Optional[float] = None
    filter_tags: Optional[List[str]] = None

class ChatRequest(BaseModel):
    question: str
    knowledge_base_id: Optional[str] = None
    chat_history: Optional[List[ChatHistoryItem]] = None
    params: Optional[ChatParams] = None

async def rag_chat_stream(request: ChatRequest):
    question = request.question
    
    # Extract params with fallbacks
    temperature = 0.3
    top_k = 13
    score_threshold = 0.65
    max_tokens = 1024
    filter_tags = None
    
    if request.params:
        if request.params.temperature is not None:
            temperature = request.params.temperature
        if request.params.top_k is not None:
            top_k = request.params.top_k
        if request.params.score_threshold is not None:
            score_threshold = request.params.score_threshold
        if request.params.max_tokens is not None:
            max_tokens = request.params.max_tokens
        if request.params.filter_tags is not None:
            filter_tags = request.params.filter_tags

    sources = []
    context_str = ""
    
    # 1. 如果有指定知識庫，執行向量檢索獲取 Context
    if request.knowledge_base_id:
        try:
            kb_id = PydanticObjectId(request.knowledge_base_id)
            kb = await KnowledgeBase.get(kb_id)
            if kb:
                try:
                    # 取得提問向量
                    query_vector = await EmbeddingService.get_embedding(question)
                    # Qdrant 相似度檢索
                    raw_results = await QdrantService.search_similar(
                        collection_name=kb.qdrant_collection_name,
                        query_vector=query_vector,
                        top_k=top_k,
                        score_threshold=score_threshold,
                        filter_tags=filter_tags
                    )
                    
                    # 整理 Chunks 為 Context
                    context_parts = []
                    for item in raw_results:
                        meta = item.get("metadata", {})
                        sources.append({
                            "chunk_id": item.get("chunk_id"),
                            "content": item.get("content", ""),
                            "metadata": {
                                "filename": meta.get("filename"),
                                "page": meta.get("page"),
                                "section": meta.get("section"),
                                "chunk_index": meta.get("chunk_index"),
                                "tags": meta.get("tags", [])
                            },
                            "score": item.get("score", 0.0)
                        })
                        chunk_idx = meta.get("chunk_index")
                        chunk_idx_str = f"#{chunk_idx}" if chunk_idx is not None else "?"
                        context_parts.append(f"【來源文件：{meta.get('filename', '未知')} | 段落編號：{chunk_idx_str}】\n內容：{item.get('content', '')}")
                    
                    if context_parts:
                        context_str = "\n---\n".join(context_parts)
                except Exception as inner_e:
                    logger.error(f"Failed to perform vector search or embedding for RAG: {inner_e}")
            else:
                logger.warning(f"Knowledge base with ID {kb_id} not found.")
        except Exception as outer_e:
            logger.error(f"Invalid knowledge_base_id format or error loading KB: {outer_e}")

    # 2. 構建 System Prompt 與 Messages
    if context_str:
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
            stream=True
        )
        
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
            except Exception as parse_e:
                logger.error(f"Error parsing SSE chunk: {raw_chunk}, error: {parse_e}")
    except Exception as llm_e:
        logger.error(f"Failed to stream from vLLM: {llm_e}")
        error_msg = f"[系統連線錯誤] 無法從 vLLM 服務取得回覆：{str(llm_e)}"
        yield f"event: chunk\ndata: {json.dumps({'type': 'content', 'content': error_msg}, ensure_ascii=False)}\n\n"

    # 4. 傳送 done 事件與 sources 事件給前端
    yield f"event: chunk\ndata: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
    yield f"event: sources\ndata: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"

@router.post("/chat")
async def chat_stub(request: ChatRequest):
    return StreamingResponse(rag_chat_stream(request), media_type="text/event-stream")

@router.get("/history")
async def history_stub():
    return {"total": 0, "items": []}

@router.delete("/history/{session_id}")
async def delete_history_stub(session_id: str):
    return {"message": "刪除成功"}
