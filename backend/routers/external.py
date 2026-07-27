import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from beanie import PydanticObjectId

from routers.rag import ChatRequest, rag_chat_stream
from models.external_api_key import ExternalApiKey
from models.external_chat_log import ExternalChatLog, SourceSummaryItem
from models.app_registration import AppRegistration
from models.knowledge_base import KnowledgeBase
from schemas.ingest import IngestTriggerRequest
from services.arq_pool import ArqPool
from utils.security import verify_external_api_key, verify_ingest_api_key

logger = logging.getLogger("airag.external_router")
# 供公司內網外部應用串接使用，掛 verify_external_api_key（X-API-Key 標頭）驗證，
# 與內部 get_current_user JWT 各自獨立、不共用（依 NewFeaturesPlan_ExternalApiTestPlan.md 第 10 節決議）
router = APIRouter(prefix="/external", tags=["External API"])


def _parse_sse_event(evt: str):
    """
    解析 rag_chat_stream() 產生的單一完整 SSE 事件字串，回傳 (event_name, data_dict)。
    """
    event_name = None
    data = None
    for line in evt.split("\n"):
        line = line.strip()
        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_str = line[len("data:"):].strip()
            if data_str:
                try:
                    data = json.loads(data_str)
                except Exception:
                    data = None
    return event_name, data


async def _external_chat_with_logging(request: ChatRequest, api_key_id: Optional[PydanticObjectId]):
    """
    包一層在 rag_chat_stream() 外面：原樣轉發每個 SSE 事件（維持既有串流體驗），
    同時在旁路累積回答內容與來源，於串流結束時（正常結束／中途斷線／例外皆然，
    見 try...finally 結構）寫入一筆 ExternalChatLog 稽核紀錄。
    只包在這裡，不修改 rag_chat_stream() 本體，內部 /api/rag/chat 完全不受影響。
    """
    external_user = request.params.external_user if request.params else None
    custom_prompt = request.params.custom_system_prompt if request.params else None
    search_type = request.params.search_type if request.params else None

    accumulated_content = ""
    sources_data = []
    start_time = datetime.utcnow()

    try:
        async for evt in rag_chat_stream(request):
            event_name, data = _parse_sse_event(evt)
            if event_name == "chunk" and data and data.get("type") == "content":
                accumulated_content += data.get("content", "")
            elif event_name == "message" and data and isinstance(data.get("delta"), str):
                # 提前 return 的固定提示訊息（例如未達 AI 總結門檻）為整段覆蓋，非累加
                accumulated_content = data["delta"]
            elif event_name == "sources" and data:
                sources_data = data.get("sources") or []
            yield evt
    finally:
        try:
            elapsed_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            sources_summary = [
                SourceSummaryItem(
                    filename=(s.get("metadata") or {}).get("filename"),
                    chunk_id=s.get("chunk_id"),
                    chunk_index=(s.get("metadata") or {}).get("chunk_index"),
                    score=s.get("score"),
                    semantic_score=s.get("semantic_score")
                )
                for s in sources_data
            ]
            await ExternalChatLog(
                api_key_id=api_key_id,
                employee_id=external_user.employee_id if external_user else "",
                employee_name=external_user.name if external_user else "",
                department_code=external_user.department_code if external_user else "",
                department_name=external_user.department_name if external_user else "",
                job_title_name=external_user.job_title_name if external_user else "",
                job_title_level=external_user.job_title_level if external_user else 0,
                knowledge_base_id=request.knowledge_base_id,
                search_type=search_type,
                question=request.question,
                answer=accumulated_content,
                sources_summary=sources_summary,
                custom_system_prompt=custom_prompt,
                elapsed_ms=elapsed_ms
            ).insert()
        except Exception as log_err:
            # 旁路稽核寫入採 best-effort，比照 rag.py 既有的 RetrievalStatsService.record 作法，
            # 失敗只記警告 log，不能讓稽核紀錄寫入失敗連帶影響或掩蓋已送達使用者的串流結果
            logger.warning(f"[ExternalChatLog] 稽核紀錄寫入失敗（不影響本次對話流程）: {log_err}")


@router.post("/chat")
async def external_chat(
    request: ChatRequest,
    api_key: ExternalApiKey = Depends(verify_external_api_key)
):
    if not request.params or not request.params.external_user:
        raise HTTPException(
            status_code=400,
            detail="外部應用呼叫必須於 params.external_user 帶入使用者身分資訊"
        )
    return StreamingResponse(
        _external_chat_with_logging(request, api_key.id),
        media_type="text/event-stream"
    )


@router.post("/ingest/trigger", status_code=202)
async def trigger_ingest(
    request: IngestTriggerRequest,
    api_key: ExternalApiKey = Depends(verify_ingest_api_key)
):
    """
    多應用 RAG 同步觸發端點（見 MULTI_APP_RAG_SYNC_PLAN.md 2.1 節）。
    立即回應 202 並將實際切分/embedding/寫入 Qdrant 交給 arq 背景佇列處理，
    避免呼叫端 HTTP 連線因等待處理完成而逾時／斷線。
    """
    # 「未登錄」與「已停用」的處理方式完全不同（前者要 POST 新建、後者要 PUT 改 is_active），
    # 故分開回報，避免呼叫端拿到同一句訊息而無法判斷該做什麼
    app_reg = await AppRegistration.find_one(AppRegistration.app_id == request.app_id)
    if not app_reg:
        raise HTTPException(
            status_code=400,
            detail=f"appId '{request.app_id}' 未登錄，請先以 POST /api/app-registrations 建立登錄資料"
        )
    if not app_reg.is_active:
        raise HTTPException(
            status_code=400,
            detail=f"appId '{request.app_id}' 已登錄但目前為停用狀態，請以 PUT /api/app-registrations/{request.app_id} 設定 is_active=true"
        )

    if app_reg.report_mode == "webhook" and not request.callback_url:
        raise HTTPException(status_code=400, detail="report_mode='webhook' 的 App 呼叫觸發端點時必須帶 callbackUrl")

    try:
        kb_object_id = PydanticObjectId(request.knowledge_base_id)
    except Exception:
        raise HTTPException(status_code=400, detail="無效的 knowledgeBaseId 格式")

    kb = await KnowledgeBase.get(kb_object_id)
    if not kb:
        raise HTTPException(status_code=400, detail=f"knowledgeBaseId '{request.knowledge_base_id}' 對應的知識庫不存在")

    job_payload = {
        "app_id": request.app_id,
        "doc_type": request.doc_type,
        "source_id": request.source_id,
        "title": request.title,
        "target_version": request.target_version,
        "action": request.action,
        "knowledge_base_id": request.knowledge_base_id,
        "callback_url": request.callback_url,
        "permissions": request.permissions.model_dump() if request.permissions else None
    }

    pool = await ArqPool.get_pool()
    job = await pool.enqueue_job("process_ingest_task", job_payload)

    return {
        "success": True,
        "message": "Task queued successfully",
        "taskId": job.job_id
    }
