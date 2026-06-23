from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from beanie import PydanticObjectId
import time
import json
import asyncio
import logging

from utils.security import get_current_user
from services.llm_service import LLMService
from models.prompt_template import PromptTemplate
from models.prompt_test_record import PromptTestRecord

logger = logging.getLogger("airag.prompt_router")
router = APIRouter(prefix="/prompt", tags=["Prompt"], dependencies=[Depends(get_current_user)])

# --- Request / Response Schemas ---

class PreviewRequest(BaseModel):
    context: str
    question: str
    system_prompt: str
    user_prompt_template: str

class PreviewResponse(BaseModel):
    rendered_system_prompt: str
    rendered_user_prompt: str
    total_estimated_tokens: int

class Variant(BaseModel):
    label: str
    system_prompt: str
    user_prompt_template: str
    params: Optional[Dict[str, Any]] = None

class ABTestRequest(BaseModel):
    context: str
    question: str
    variants: List[Variant]

class ABTestResult(BaseModel):
    label: str
    answer: str
    params: Dict[str, Any]
    elapsed_ms: int

class ABTestResponse(BaseModel):
    results: List[ABTestResult]

class TemplateCreateRequest(BaseModel):
    name: str
    system_prompt: Optional[str] = None
    user_prompt_template: str

class TemplateResponse(BaseModel):
    id: str
    name: str
    system_prompt: Optional[str] = None
    user_prompt_template: str
    is_default: bool
    created_at: datetime

class RecordCreateRequest(BaseModel):
    name: str
    system_prompt: str
    user_prompt_template: str
    context: str
    question: str
    results: List[Dict[str, Any]]

class RecordResponse(BaseModel):
    id: str
    name: str
    system_prompt: str
    user_prompt_template: str
    context: str
    question: str
    results: List[Dict[str, Any]]
    created_at: datetime

# --- Endpoints ---

@router.post("/generate")
async def generate_stub():
    return {"message": "Prompt generation stub."}

@router.post("/preview", response_model=PreviewResponse)
async def preview_prompt(req: PreviewRequest):
    rendered_system_prompt = req.system_prompt
    rendered_user_prompt = req.user_prompt_template.replace("{context}", req.context).replace("{question}", req.question)
    
    # Calculate estimated tokens matching the frontend logic (length * 1.3)
    total_len = len(rendered_system_prompt) + len(rendered_user_prompt)
    total_estimated_tokens = int(round(total_len * 1.3))
    
    return PreviewResponse(
        rendered_system_prompt=rendered_system_prompt,
        rendered_user_prompt=rendered_user_prompt,
        total_estimated_tokens=total_estimated_tokens
    )

@router.post("/ab-test")
async def ab_test_prompt(req: ABTestRequest):
    async def ab_test_stream_generator():
        queue = asyncio.Queue()
        
        async def run_variant(index: int, variant: Variant):
            rendered_user = variant.user_prompt_template.replace("{context}", req.context).replace("{question}", req.question)
            messages = [
                {"role": "system", "content": variant.system_prompt},
                {"role": "user", "content": rendered_user}
            ]
            params = variant.params or {}
            temperature = params.get("temperature", 0.7)
            max_tokens = params.get("max_tokens", 1024)
            
            start_time = time.time()
            try:
                vllm_stream = await LLMService.chat_completion(
                    messages=messages,
                    temperature=float(temperature),
                    max_tokens=int(max_tokens),
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
                                await queue.put({"index": index, "type": "reasoning", "content": reasoning_chunk})
                            if content_chunk:
                                await queue.put({"index": index, "type": "content", "content": content_chunk})
                    except Exception as parse_e:
                        logger.error(f"Error parsing SSE chunk: {raw_chunk}, error: {parse_e}")
            except Exception as e:
                logger.error(f"Failed to stream variant {index} ({variant.label}): {e}")
                await queue.put({"index": index, "type": "error", "content": f"Error during generation: {str(e)}"})
            finally:
                elapsed_ms = int((time.time() - start_time) * 1000)
                await queue.put({"index": index, "type": "done", "elapsed_ms": elapsed_ms})
                
        # Start all tasks in parallel
        tasks = []
        for idx, var in enumerate(req.variants):
            tasks.append(asyncio.create_task(run_variant(idx, var)))
            
        finished_count = 0
        num_variants = len(req.variants)
        
        while finished_count < num_variants:
            item = await queue.get()
            if item["type"] == "done":
                finished_count += 1
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            
    return StreamingResponse(ab_test_stream_generator(), media_type="text/event-stream")

# --- Templates CRUD ---

@router.get("/templates", response_model=List[TemplateResponse])
async def list_templates():
    try:
        templates = await PromptTemplate.find_all().to_list()
        return [
            TemplateResponse(
                id=str(t.id),
                name=t.name,
                system_prompt=t.system_prompt,
                user_prompt_template=t.user_prompt_template,
                is_default=t.is_default,
                created_at=t.created_at
            ) for t in templates
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取範本失敗: {str(e)}"
        )

@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(req: TemplateCreateRequest, current_user: str = Depends(get_current_user)):
    try:
        template = PromptTemplate(
            name=req.name,
            system_prompt=req.system_prompt,
            user_prompt_template=req.user_prompt_template,
            created_by=current_user,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        await template.insert()
        return TemplateResponse(
            id=str(template.id),
            name=template.name,
            system_prompt=template.system_prompt,
            user_prompt_template=template.user_prompt_template,
            is_default=template.is_default,
            created_at=template.created_at
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"儲存範本失敗: {str(e)}"
        )

@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, current_user: str = Depends(get_current_user)):
    try:
        db_id = PydanticObjectId(template_id)
        template = await PromptTemplate.get(db_id)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="找不到指定的範本"
            )
        await template.delete()
        return {"message": "範本刪除成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刪除範本失敗: {str(e)}"
        )

# --- Test Records CRUD ---

@router.get("/records", response_model=List[RecordResponse])
async def list_records():
    try:
        # Sort descending by created_at to see latest first
        records = await PromptTestRecord.find_all().sort(-PromptTestRecord.created_at).to_list()
        return [
            RecordResponse(
                id=str(r.id),
                name=r.name,
                system_prompt=r.system_prompt,
                user_prompt_template=r.user_prompt_template,
                context=r.context,
                question=r.question,
                results=r.results,
                created_at=r.created_at
            ) for r in records
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取歷史紀錄失敗: {str(e)}"
        )

@router.post("/records", response_model=RecordResponse, status_code=status.HTTP_201_CREATED)
async def create_record(req: RecordCreateRequest, current_user: str = Depends(get_current_user)):
    try:
        record = PromptTestRecord(
            name=req.name,
            system_prompt=req.system_prompt,
            user_prompt_template=req.user_prompt_template,
            context=req.context,
            question=req.question,
            results=req.results,
            created_by=current_user,
            created_at=datetime.utcnow()
        )
        await record.insert()
        return RecordResponse(
            id=str(record.id),
            name=record.name,
            system_prompt=record.system_prompt,
            user_prompt_template=record.user_prompt_template,
            context=record.context,
            question=record.question,
            results=record.results,
            created_at=record.created_at
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"儲存紀錄失敗: {str(e)}"
        )

@router.delete("/records/{record_id}")
async def delete_record(record_id: str, current_user: str = Depends(get_current_user)):
    try:
        db_id = PydanticObjectId(record_id)
        record = await PromptTestRecord.get(db_id)
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="找不到指定的歷史紀錄"
            )
        await record.delete()
        return {"message": "歷史紀錄刪除成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刪除歷史紀錄失敗: {str(e)}"
        )
