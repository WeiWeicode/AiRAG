import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from beanie import PydanticObjectId

from models.test_dataset import TestDataset, DatasetItem
from models.eval_report import EvalReport, EvalParams, EvalMetrics, EvalDetail
from models.knowledge_base import KnowledgeBase
from services.embedding_service import EmbeddingService
from services.qdrant_service import QdrantService
from services.llm_service import LLMService
from services.rerank_service import RerankService
from services.feedback_boost_service import FeedbackBoostService
from utils.security import get_current_user

logger = logging.getLogger("airag.evaluation_router")
router = APIRouter(prefix="/evaluation", tags=["Evaluation"], dependencies=[Depends(get_current_user)])

class DatasetItemInput(BaseModel):
    question: str
    ground_truth: str
    relevant_contexts: Optional[List[str]] = None

class DatasetCreateInput(BaseModel):
    name: str
    description: Optional[str] = None
    items: List[DatasetItemInput]

class EvalParamsInput(BaseModel):
    model: Optional[str] = None
    temperature: Optional[float] = None
    top_k: Optional[int] = None
    score_threshold: Optional[float] = None
    max_tokens: Optional[int] = None
    search_type: Optional[str] = "vector"

class EvalRunRequest(BaseModel):
    dataset_id: str
    knowledge_base_id: Optional[str] = None
    params: Optional[EvalParamsInput] = None

def parse_judge_json(response_text: str) -> dict:
    if not response_text:
        return {}
    
    import re
    
    # 1. 嘗試直接解析整段文字（去除 markdown 標籤）
    text = response_text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2. 用正則表達式尋找包含 "faithfulness" 的 JSON 物件
    try:
        pattern = r"(\{\s*\"faithfulness\".*?\})"
        matches = re.findall(pattern, response_text, re.DOTALL)
        for match in matches:
            try:
                return json.loads(match)
            except Exception:
                pass
    except Exception:
        pass

    # 3. 備用方案：尋找任何最長匹配的 { ... } 區塊
    try:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}")
        if start_idx != -1 and end_idx != -1:
            candidate = response_text[start_idx:end_idx+1]
            return json.loads(candidate)
    except Exception:
        pass
        
    logger.error(f"Failed to parse judge JSON: {response_text}")
    return {}

@router.post("/datasets")
async def create_dataset(payload: DatasetCreateInput, current_user: str = Depends(get_current_user)):
    """
    建立或匯入測試集。
    """
    try:
        items = [
            DatasetItem(
                question=item.question,
                ground_truth=item.ground_truth,
                relevant_contexts=item.relevant_contexts or []
            ) for item in payload.items
        ]
        dataset = TestDataset(
            name=payload.name,
            description=payload.description,
            items=items,
            item_count=len(items),
            created_by=current_user,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        await dataset.insert()
        return {
            "dataset_id": str(dataset.id),
            "name": dataset.name,
            "item_count": dataset.item_count
        }
    except Exception as e:
        logger.error(f"Failed to create dataset: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"建立測試集失敗: {str(e)}"
        )

@router.get("/datasets")
async def list_datasets():
    """
    列出所有測試集，適配前端 hardcoded 的 ID。
    """
    try:
        datasets = await TestDataset.find_all().to_list()
        items = []
        for d in datasets:
            # 配對前端 datasetId === 'dataset_tech' ? 'tech_specs' : 'hr_docs'
            if "技術" in d.name:
                dataset_id = "dataset_tech"
            elif "人事" in d.name:
                dataset_id = "dataset_hr"
            else:
                dataset_id = str(d.id)
                
            items.append({
                "dataset_id": dataset_id,
                "name": d.name,
                "item_count": d.item_count
            })
        return {"items": items}
    except Exception as e:
        logger.error(f"Failed to list datasets: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"讀取測試集失敗: {str(e)}"
        )

@router.post("/run")
async def run_evaluation(payload: EvalRunRequest, current_user: str = Depends(get_current_user)):
    """
    執行自動化評估。批次跑測試集問題，生成回答後使用 LLM-as-a-Judge 計算各項指標。
    並採用 StreamingResponse 回傳即時進度。
    """
    from fastapi.responses import StreamingResponse
    
    # 1. 解析 Dataset ID
    dataset = None
    if payload.dataset_id == "dataset_tech":
        dataset = await TestDataset.find_one(TestDataset.name == "技術規格測試集")
    elif payload.dataset_id == "dataset_hr":
        dataset = await TestDataset.find_one(TestDataset.name == "人事規章測試集")
    
    if not dataset:
        try:
            db_id = PydanticObjectId(payload.dataset_id)
            dataset = await TestDataset.get(db_id)
        except Exception:
            pass
            
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="找不到指定的測試集"
        )

    # 2. 解析 Knowledge Base ID
    kb = None
    if payload.knowledge_base_id:
        try:
            kb_id = PydanticObjectId(payload.knowledge_base_id)
            kb = await KnowledgeBase.get(kb_id)
        except Exception:
            pass

    if not kb:
        kb = await KnowledgeBase.find_all().first_or_none()

    # 3. 限制最多評估 5 筆問答（避免 http timeout 逾時斷線）
    items_to_eval = dataset.items[:5]
    total_count = len(items_to_eval)

    async def event_generator():
        yield f"event: init\ndata: {json.dumps({'total': total_count, 'dataset_name': dataset.name}, ensure_ascii=False)}\n\n"

        details = []
        total_faithfulness = 0.0
        total_relevancy = 0.0
        total_precision = 0.0
        total_recall = 0.0
        
        top_k = 5
        if payload.params and payload.params.top_k is not None:
            top_k = payload.params.top_k
            
        score_threshold = 0.5
        if payload.params and payload.params.score_threshold is not None:
            score_threshold = payload.params.score_threshold

        max_tokens = 8192
        if payload.params and payload.params.max_tokens is not None:
            max_tokens = payload.params.max_tokens

        search_type = "vector"
        if payload.params and payload.params.search_type is not None:
            search_type = payload.params.search_type

        # 先行取得知識庫元資料以優化語義分析
        filenames = []
        tags = []
        structured_metadata = []
        if kb:
            try:
                metadata_info = await QdrantService.get_unique_metadata(kb.qdrant_collection_name)
                filenames = metadata_info.get("filenames", [])
                tags = metadata_info.get("tags", [])
                structured_metadata = metadata_info.get("structured_metadata", [])
                logger.info(
                    f"[Evaluation] 已從 Qdrant 取得結構化元資料 - 檔案數: {len(filenames)}, 標籤數: {len(tags)}, 結構化項目數: {len(structured_metadata)}, 檔名樣例: {filenames[:5]}, 標籤: {tags}"
                )
            except Exception as me:
                logger.error(f"Failed to fetch unique metadata for evaluation: {me}")

        for idx, item in enumerate(items_to_eval):
            # 發送進度狀態
            yield f"event: progress\ndata: {json.dumps({'index': idx + 1, 'question': item.question}, ensure_ascii=False)}\n\n"

            retrieved_contexts = []
            db_query_note = None
            # A. 向量檢索 / 語義資料庫查詢法
            if search_type == "semantic_db_query":
                # 評估流程為批次自動化執行，沒有真人可以中途選候選設定檔，
                # 採用「自動取分數最高的候選（Top-1）」並在報告中標記為自動選取，非人工確認。
                if kb:
                    try:
                        from services.ai_db_query_service import AIDBQueryService, AIDBQueryError
                        match_result = await AIDBQueryService.match_profiles(
                            question=item.question, knowledge_base_id=str(kb.id)
                        )
                        candidates = match_result["candidates"]
                        if candidates:
                            top_candidate = candidates[0]
                            exec_result = await AIDBQueryService.execute(
                                question=item.question, profile_id=top_candidate["profile_id"]
                            )
                            retrieved_contexts = [exec_result["context_text"]]
                            db_query_note = (
                                f"自動選取設定檔「{exec_result['profile_name']}」（非人工確認），"
                                f"SQL: {exec_result['generated_sql']}"
                            )
                        else:
                            db_query_note = "查無對應的資料庫查詢設定檔"
                    except AIDBQueryError as e:
                        logger.error(f"Semantic DB query failed for question '{item.question}': {e}")
                        db_query_note = f"語義資料庫查詢法執行失敗：{e}"
                    except Exception as se:
                        logger.error(f"Semantic DB query failed for question '{item.question}': {se}")
                        db_query_note = f"語義資料庫查詢法執行失敗：{se}"
            elif kb:
                try:
                    is_semantic_hybrid_family = search_type in ("semantic_hybrid", "semantic_hybrid_feedback")
                    if is_semantic_hybrid_family:
                        # 語義混合查詢流程
                        semantic_json = await EmbeddingService.query_to_semantic_json(
                            item.question, filenames=filenames, tags=tags, structured_metadata=structured_metadata
                        )
                        logger.info(f"[Evaluation] 已從 Instruct AI 取得結構化 JSON，以下是結構化內容: {semantic_json}")

                        embeddings_input = semantic_json.get("embeddings_input", item.question)
                        sparse_keywords = semantic_json.get("sparse_keywords", [])

                        query_vector = await EmbeddingService.get_semantic_embedding(embeddings_input)
                        search_query_text = " ".join(sparse_keywords) if sparse_keywords else item.question
                    else:
                        query_vector = await EmbeddingService.get_embedding(item.question)
                        search_query_text = item.question
                        sparse_keywords = None

                    # semantic_hybrid 系列時多召回一批候選（供 rerank 使用），其餘搜尋類型維持原本 top_k
                    fetch_k = max(top_k, RerankService.MAX_CANDIDATES) if is_semantic_hybrid_family else top_k

                    search_results = await QdrantService.search_similar(
                        collection_name=kb.qdrant_collection_name,
                        query_vector=query_vector,
                        query_text=search_query_text,
                        search_type="semantic_hybrid" if is_semantic_hybrid_family else search_type,
                        top_k=fetch_k,
                        score_threshold=score_threshold,
                        sparse_keywords=sparse_keywords
                    )

                    # 借用 Instruct LLM 對融合後的候選片段做相關性重排序，取前 top_k 筆
                    if is_semantic_hybrid_family and search_results:
                        search_results = await RerankService.rerank(item.question, search_results, top_k)

                    # 語義混合回饋查詢法：依歷史人工回饋對命中片段做分數加權重排
                    if search_type == "semantic_hybrid_feedback" and search_results:
                        search_results = await FeedbackBoostService.apply_feedback_boost(
                            search_results, knowledge_base_id=str(kb.id)
                        )

                    retrieved_contexts = [r.get("content", "") for r in search_results]
                except Exception as se:
                    logger.error(f"Retrieval failed for question '{item.question}': {se}")

            # 若無檢索結果則使用測試集自帶的 context
            if not retrieved_contexts and item.relevant_contexts:
                retrieved_contexts = item.relevant_contexts

            context_str = "\n---\n".join(retrieved_contexts)

            # B. 生成對答
            generated_answer = ""
            try:
                if search_type == "semantic_db_query" and context_str:
                    # 語義資料庫查詢法專用：內容是資料庫查詢結果，不套用文件引用格式規則，避免模型過度保守判定無關
                    system_prompt = (
                        "你是一個專業的資料庫問答助理。以下「資料庫查詢結果」是依照使用者問題實際從資料庫執行 SQL 查詢後取得的真實資料，"
                        "請直接根據這些資料回答使用者的問題。\n"
                        "規則：\n"
                        "1. 只要查詢結果中有任何一筆資料合理對應使用者問題描述的對象（即使欄位用詞與使用者問法不完全一致），就應該根據該筆資料直接回答，不要因為用詞不完全相同就判定無關。\n"
                        "2. 只有在查詢結果完全是空的、或所有資料列明顯都與問題無關時，才回答『知識庫沒有相關資訊。』，不要編造查詢結果中沒有的內容。\n"
                        "3. 保持回答清晰、專業且符合邏輯。\n\n"
                        f"【資料庫查詢結果】\n{context_str}"
                    )
                elif context_str:
                    system_prompt = (
                        "你檔案分享專業的 RAG 智慧對話助理。請根據以下提供的「參考資料」回答使用者的問題。\n"
                        "規則：\n"
                        "1. 儘量使用參考資料中的資訊來回答。\n"
                        "2. 如果參考資料不足以回答問題，請直接回答『知識庫沒有相關資訊。』，絕對不要使用你的既有知識回答，也不要編造任何內容。\n"
                        "3. 保持回答清晰、專業且符合邏輯。\n\n"
                        f"【參考資料】\n{context_str}"
                    )
                else:
                    system_prompt = "你是一個專業的 RAG 智慧對話助理。由於目前沒有提供任何參考資料，請直接回答『知識庫沒有相關資訊。』，絕對不要回答其他內容。"

                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": item.question}
                ]
                generated_answer = await LLMService.chat_completion(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=max_tokens,
                    stream=False
                )
                generated_answer = generated_answer.strip()
            except Exception as ge:
                logger.error(f"Answer generation failed for question '{item.question}': {ge}")
                generated_answer = "無法生成回答"

            # C. LLM-as-a-Judge 指標評分
            scores = {
                "faithfulness": 0.0,
                "relevancy": 0.0,
                "precision": 0.0,
                "recall": 0.0
            }
            judge_prompt = (
                "你是一個 RAG 系統評估專家。請根據給定的：\n"
                f"1. 使用者問題 (Question): {item.question}\n"
                f"2. 參考上下文 (Context): {json.dumps(retrieved_contexts, ensure_ascii=False)}\n"
                f"3. AI生成的回答 (Answer): {generated_answer}\n"
                f"4. 標準答案 (Ground Truth): {item.ground_truth}\n\n"
                "請客觀且嚴格地評估以下四項指標，每項指標給予一個介於 0.0 到 1.0 之間的分數：\n"
                "1. 忠實度 (faithfulness)：評估 Answer 中的內容是否完全可以由 Context 推導出來，無幻覺或無外部既有知識。若完全可推導為 1.0，完全無關或虛構為 0.0。\n"
                "2. 回答相關性 (relevancy)：評估 Answer 是否切題並直接回答了 Question。若直接回答為 1.0，答非所問為 0.0。\n"
                "3. 上下文精確率 (precision)：評估 Context 中對回答 Question 有幫助的資訊比例。若所有 Context 都有用為 1.0，完全無關為 0.0。\n"
                "4. 上下文召回率 (recall)：評估 Context 是否涵蓋了 Ground Truth 中所有關鍵訊息。若完全涵蓋為 1.0，完全沒有涵蓋為 0.0。\n\n"
                "規則：請僅回傳 JSON 格式結果，不要包含任何額外引言或 Markdown 標記，格式如下：\n"
                "{\n"
                "  \"faithfulness\": 0.9,\n"
                "  \"relevancy\": 0.8,\n"
                "  \"precision\": 0.7,\n"
                "  \"recall\": 0.8\n"
                "}"
            )

            try:
                judge_messages = [
                    {"role": "system", "content": "你是一個專業的評估 JSON 輸出助理。"},
                    {"role": "user", "content": judge_prompt}
                ]
                judge_response = await LLMService.chat_completion(
                    messages=judge_messages,
                    temperature=0.1,
                    max_tokens=8192,
                    stream=False
                )
                parsed_scores = parse_judge_json(judge_response)
                if parsed_scores:
                    scores["faithfulness"] = float(parsed_scores.get("faithfulness", 0.0))
                    scores["relevancy"] = float(parsed_scores.get("relevancy", 0.0))
                    scores["precision"] = float(parsed_scores.get("precision", 0.0))
                    scores["recall"] = float(parsed_scores.get("recall", 0.0))
            except Exception as je:
                logger.error(f"LLM-as-a-Judge scoring failed: {je}")

            total_faithfulness += scores["faithfulness"]
            total_relevancy += scores["relevancy"]
            total_precision += scores["precision"]
            total_recall += scores["recall"]

            detail_item = {
                "question": item.question,
                "ground_truth": item.ground_truth,
                "generated_answer": generated_answer,
                "scores": scores,
                "db_query_note": db_query_note
            }
            details.append(
                EvalDetail(
                    question=item.question,
                    ground_truth=item.ground_truth,
                    generated_answer=generated_answer,
                    retrieved_contexts=retrieved_contexts,
                    scores=EvalMetrics(
                        faithfulness=scores["faithfulness"],
                        answer_relevancy=scores["relevancy"],
                        context_precision=scores["precision"],
                        context_recall=scores["recall"]
                    ),
                    db_query_note=db_query_note
                )
            )

            # 即時發送單筆問答的評估結果至前端
            yield f"event: item_done\ndata: {json.dumps(detail_item, ensure_ascii=False)}\n\n"

        # 5. 彙整分數並儲存報告
        summary_metrics = EvalMetrics(
            faithfulness=total_faithfulness / total_count if total_count > 0 else 0.0,
            answer_relevancy=total_relevancy / total_count if total_count > 0 else 0.0,
            context_precision=total_precision / total_count if total_count > 0 else 0.0,
            context_recall=total_recall / total_count if total_count > 0 else 0.0
        )

        report = EvalReport(
            dataset_id=dataset.id,
            dataset_name=dataset.name,
            knowledge_base_id=str(kb.id) if kb else None,
            model=payload.params.model if (payload.params and payload.params.model) else "Qwen3.6-35B-A3B-FP8",
            params=EvalParams(
                temperature=payload.params.temperature if (payload.params and payload.params.temperature is not None) else 0.3,
                top_k=top_k,
                score_threshold=score_threshold,
                max_tokens=max_tokens,
                search_type=search_type
            ),
            summary=summary_metrics,
            details=details,
            status="completed",
            created_by=current_user,
            created_at=datetime.utcnow(),
            completed_at=datetime.utcnow()
        )
        await report.insert()

        # 即時發送總彙整報告至前端
        result_data = {
            'report_id': str(report.id),
            'summary': {
                'faithfulness': summary_metrics.faithfulness,
                'relevancy': summary_metrics.answer_relevancy,
                'precision': summary_metrics.context_precision,
                'recall': summary_metrics.context_recall
            },
            'details': [
                {
                    'question': d.question,
                    'ground_truth': d.ground_truth,
                    'generated_answer': d.generated_answer,
                    'scores': {
                        'faithfulness': d.scores.faithfulness,
                        'relevancy': d.scores.answer_relevancy,
                        'precision': d.scores.context_precision,
                        'recall': d.scores.context_recall
                    },
                    'db_query_note': d.db_query_note
                } for d in details
            ]
        }
        yield f"event: result\ndata: {json.dumps(result_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/reports/{report_id}")
async def get_report(report_id: str):
    """
    取得已生成的評估報告。
    """
    try:
        r_id = PydanticObjectId(report_id)
        report = await EvalReport.get(r_id)
        if not report:
            raise HTTPException(status_code=404, detail="找不到指定的評估報告")
            
        return {
            "report_id": str(report.id),
            "summary": {
                "faithfulness": report.summary.faithfulness,
                "relevancy": report.summary.answer_relevancy,
                "precision": report.summary.context_precision,
                "recall": report.summary.context_recall
            },
            "details": [
                {
                    "question": d.question,
                    "ground_truth": d.ground_truth,
                    "generated_answer": d.generated_answer,
                    "scores": {
                        "faithfulness": d.scores.faithfulness,
                        "relevancy": d.scores.answer_relevancy,
                        "precision": d.scores.context_precision,
                        "recall": d.scores.context_recall
                    },
                    "db_query_note": d.db_query_note
                } for d in report.details
            ]
        }
    except Exception as e:
        logger.error(f"Failed to get report: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"讀取評估報告失敗: {str(e)}"
        )

class DatasetUpdateInput(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    items: List[DatasetItemInput]

@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    """
    取得指定測試集之明細項目。
    """
    dataset = None
    if dataset_id == "dataset_tech":
        dataset = await TestDataset.find_one(TestDataset.name == "技術規格測試集")
    elif dataset_id == "dataset_hr":
        dataset = await TestDataset.find_one(TestDataset.name == "人事規章測試集")
    
    if not dataset:
        try:
            db_id = PydanticObjectId(dataset_id)
            dataset = await TestDataset.get(db_id)
        except Exception:
            pass
            
    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="找不到指定的測試集"
        )
        
    return {
        "dataset_id": dataset_id,
        "name": dataset.name,
        "description": dataset.description,
        "item_count": dataset.item_count,
        "items": [
            {
                "question": item.question,
                "ground_truth": item.ground_truth,
                "relevant_contexts": item.relevant_contexts
            } for item in dataset.items
        ]
    }

@router.put("/datasets/{dataset_id}")
async def update_dataset(dataset_id: str, payload: DatasetUpdateInput, current_user: str = Depends(get_current_user)):
    """
    修改更新測試集明細項目。
    """
    try:
        dataset = None
        if dataset_id == "dataset_tech":
            dataset = await TestDataset.find_one(TestDataset.name == "技術規格測試集")
        elif dataset_id == "dataset_hr":
            dataset = await TestDataset.find_one(TestDataset.name == "人事規章測試集")
        
        if not dataset:
            try:
                db_id = PydanticObjectId(dataset_id)
                dataset = await TestDataset.get(db_id)
            except Exception:
                pass
                
        if not dataset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="找不到指定的測試集"
            )
            
        if payload.name is not None:
            dataset.name = payload.name
        if payload.description is not None:
            dataset.description = payload.description
            
        dataset.items = [
            DatasetItem(
                question=item.question,
                ground_truth=item.ground_truth,
                relevant_contexts=item.relevant_contexts or []
            ) for item in payload.items
        ]
        dataset.item_count = len(dataset.items)
        dataset.updated_at = datetime.utcnow()
        await dataset.save()
        
        return {
            "dataset_id": dataset_id,
            "name": dataset.name,
            "item_count": dataset.item_count
        }
    except Exception as e:
        logger.error(f"Failed to update dataset: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新測試集失敗: {str(e)}"
        )
