import csv
import io
import json
import logging
from datetime import datetime
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from beanie import PydanticObjectId

from models.feedback import Feedback, FeedbackSourceChunk
from models.test_dataset import TestDataset, DatasetItem
from utils.security import get_current_user

logger = logging.getLogger("airag.feedback_router")
router = APIRouter(prefix="/feedback", tags=["Feedback"], dependencies=[Depends(get_current_user)])

class FeedbackSourceChunkPayload(BaseModel):
    filename: Optional[str] = None
    chunk_index: Optional[Any] = None

class FeedbackCreate(BaseModel):
    chat_message_id: str
    is_correct: bool
    correct_answer: Optional[str] = None
    error_type: Optional[str] = None
    note: Optional[str] = None
    question: str
    ai_answer: str
    source_chunks: Optional[List[FeedbackSourceChunkPayload]] = None
    knowledge_base_id: Optional[str] = None

class FeedbackItem(BaseModel):
    feedback_id: str
    chat_message_id: str
    question: str
    ai_answer: str
    is_correct: bool
    correct_answer: Optional[str] = None
    error_type: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime

class FeedbackListResponse(BaseModel):
    total: int
    items: List[FeedbackItem]

class ExportToDatasetRequest(BaseModel):
    feedback_ids: List[str]
    target_dataset_id: Optional[str] = None
    new_dataset_name: Optional[str] = None

@router.post("", response_model=FeedbackItem, status_code=status.HTTP_201_CREATED)
async def create_feedback(request: FeedbackCreate, current_user: str = Depends(get_current_user)):
    """
    提交回饋標註。
    """
    try:
        source_chunks = None
        if request.source_chunks:
            source_chunks = [
                FeedbackSourceChunk(filename=sc.filename, chunk_index=sc.chunk_index)
                for sc in request.source_chunks
            ]

        feedback = Feedback(
            chat_message_id=request.chat_message_id,
            is_correct=request.is_correct,
            correct_answer=request.correct_answer,
            error_type=request.error_type,
            note=request.note,
            question=request.question,
            ai_answer=request.ai_answer,
            source_chunks=source_chunks,
            knowledge_base_id=request.knowledge_base_id,
            created_by=current_user,
            created_at=datetime.utcnow()
        )
        await feedback.insert()
        
        return FeedbackItem(
            feedback_id=str(feedback.id),
            chat_message_id=feedback.chat_message_id,
            question=feedback.question,
            ai_answer=feedback.ai_answer,
            is_correct=feedback.is_correct,
            correct_answer=feedback.correct_answer,
            error_type=feedback.error_type,
            note=feedback.note,
            created_at=feedback.created_at
        )
    except Exception as e:
        logger.error(f"Failed to create feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"提交回饋失敗: {str(e)}"
        )

@router.get("", response_model=FeedbackListResponse)
async def list_feedbacks(
    is_correct: Optional[bool] = Query(None),
    error_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1)
):
    """
    取得回饋標註列表。
    """
    try:
        query = {}
        if is_correct is not None:
            query["is_correct"] = is_correct
        if error_type:
            query["error_type"] = error_type

        total = await Feedback.find(query).count()
        
        # Paginated fetch sorted by newest first
        skip = (page - 1) * page_size
        feedbacks = await Feedback.find(query).sort("-created_at").skip(skip).limit(page_size).to_list()
        
        items = [
            FeedbackItem(
                feedback_id=str(fb.id),
                chat_message_id=fb.chat_message_id,
                question=fb.question,
                ai_answer=fb.ai_answer,
                is_correct=fb.is_correct,
                correct_answer=fb.correct_answer,
                error_type=fb.error_type,
                note=fb.note,
                created_at=fb.created_at
            )
            for fb in feedbacks
        ]
        
        return FeedbackListResponse(total=total, items=items)
    except Exception as e:
        logger.error(f"Failed to list feedbacks: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"獲取回饋列表失敗: {str(e)}"
        )

@router.post("/export-to-dataset")
async def export_to_dataset(request: ExportToDatasetRequest, current_user: str = Depends(get_current_user)):
    """
    將不正確的回饋標註批次匯入測試集。
    """
    try:
        object_ids = []
        for fid in request.feedback_ids:
            try:
                object_ids.append(PydanticObjectId(fid))
            except Exception:
                continue

        if not object_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="未提供有效的回饋 ID"
            )

        feedbacks = await Feedback.find({"_id": {"$in": object_ids}}).to_list()
        if not feedbacks:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="找不到對應的回饋紀錄"
            )

        # Convert feedback to DatasetItems
        new_items = []
        for fb in feedbacks:
            new_items.append(
                DatasetItem(
                    question=fb.question,
                    ground_truth=fb.correct_answer or "",
                    relevant_contexts=[],
                    source_feedback_id=fb.id
                )
            )

        if request.target_dataset_id:
            try:
                ds_id = PydanticObjectId(request.target_dataset_id)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="無效的測試集 ID 格式"
                )
            dataset = await TestDataset.get(ds_id)
            if not dataset:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="找不到指定的評估測試集"
                )
            dataset.items.extend(new_items)
            dataset.item_count = len(dataset.items)
            dataset.updated_at = datetime.utcnow()
            await dataset.save()
        else:
            name = request.new_dataset_name or f"Feedback_Sync_{datetime.utcnow().strftime('%Y-%m-%d')}"
            dataset = TestDataset(
                name=name,
                description="從用戶回饋紀錄中匯入的測試數據集",
                items=new_items,
                item_count=len(new_items),
                created_by=current_user,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            await dataset.insert()

        # Update feedback records with reference to the exported dataset ID
        for fb in feedbacks:
            fb.exported_to_dataset_id = dataset.id
            await fb.save()

        return {
            "dataset_id": str(dataset.id),
            "imported_count": len(new_items),
            "message": f"成功匯入 {len(new_items)} 筆回饋至測試集"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export feedback to dataset: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"匯出至評估測試集失敗: {str(e)}"
        )

@router.get("/export")
async def export_feedback(format: str, current_user: str = Depends(get_current_user)):
    """
    匯出回饋紀錄（CSV 或 JSON）。
    """
    try:
        feedbacks = await Feedback.find_all().sort("-created_at").to_list()
        
        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "feedback_id", "question", "ai_answer", "correct_answer", 
                "is_correct", "error_type", "note", "created_at"
            ])
            for fb in feedbacks:
                writer.writerow([
                    str(fb.id),
                    fb.question,
                    fb.ai_answer,
                    fb.correct_answer or "",
                    fb.is_correct,
                    fb.error_type or "",
                    fb.note or "",
                    fb.created_at.isoformat()
                ])
            output.seek(0)
            
            headers = {
                'Content-Disposition': 'attachment; filename="feedback_export.csv"'
            }
            return StreamingResponse(
                io.BytesIO(output.getvalue().encode('utf-8-sig')),
                media_type='text/csv',
                headers=headers
            )
        else:
            # JSON export
            data = []
            for fb in feedbacks:
                data.append({
                    "feedback_id": str(fb.id),
                    "question": fb.question,
                    "ai_answer": fb.ai_answer,
                    "correct_answer": fb.correct_answer,
                    "is_correct": fb.is_correct,
                    "error_type": fb.error_type,
                    "note": fb.note,
                    "created_at": fb.created_at.isoformat()
                })
            json_str = json.dumps(data, ensure_ascii=False, indent=2)
            headers = {
                'Content-Disposition': 'attachment; filename="feedback_export.json"'
            }
            return StreamingResponse(
                io.BytesIO(json_str.encode('utf-8')),
                media_type='application/json',
                headers=headers
            )
    except Exception as e:
        logger.error(f"Failed to export feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"匯出回饋資料失敗: {str(e)}"
        )


class BatchDeleteRequest(BaseModel):
    feedback_ids: List[str]


@router.delete("/{feedback_id}")
async def delete_feedback(feedback_id: str, current_user: str = Depends(get_current_user)):
    """
    刪除特定回饋紀錄。
    """
    try:
        fb_id = PydanticObjectId(feedback_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="無效的回饋 ID 格式"
        )
        
    feedback = await Feedback.get(fb_id)
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="找不到該回饋紀錄"
        )
        
    try:
        await feedback.delete()
        return {"message": "刪除成功"}
    except Exception as e:
        logger.error(f"Failed to delete feedback {feedback_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"刪除回饋紀錄失敗: {str(e)}"
        )


@router.post("/batch-delete")
async def batch_delete_feedbacks(request: BatchDeleteRequest, current_user: str = Depends(get_current_user)):
    """
    批次刪除回饋紀錄。
    """
    try:
        object_ids = []
        for fid in request.feedback_ids:
            try:
                object_ids.append(PydanticObjectId(fid))
            except Exception:
                continue
                
        if not object_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="未提供有效的回饋 ID"
            )
            
        await Feedback.find({"_id": {"$in": object_ids}}).delete()
        return {"message": f"成功刪除 {len(object_ids)} 筆回饋紀錄"}
    except Exception as e:
        logger.error(f"Failed to batch delete feedbacks: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"批次刪除回饋紀錄失敗: {str(e)}"
        )
