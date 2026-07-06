import json
import logging
from config import settings
from services.llm_service import LLMService
from utils.token_counter import count_tokens

logger = logging.getLogger("airag.context_summarizer")

class ContextSummarizerService:
    @classmethod
    def _bin_pack(cls, blocks: list[dict], threshold: int) -> list[list[dict]]:
        """
        依序累加分組 (Bin-Packing)，絕不拆散任何一個區塊。
        """
        groups = []
        current_group = []
        current_tokens = 0
        for block in blocks:
            block_tokens = count_tokens(block["text"])
            if not current_group:
                current_group.append(block)
                current_tokens = block_tokens
            elif current_tokens + block_tokens <= threshold:
                current_group.append(block)
                current_tokens += block_tokens
            else:
                groups.append(current_group)
                current_group = [block]
                current_tokens = block_tokens
        if current_group:
            groups.append(current_group)
        return groups

    @classmethod
    def _build_map_prompt(cls, question: str, group: list[dict], is_db: bool) -> list[dict]:
        """
        建構 Map 階段的 Prompt。
        """
        if is_db:
            system_content = (
                "你是一個專業的資料庫查詢結果整理助理。請針對使用者的問題，從下方提供的資料庫查詢結果中，萃取與問題相關的重點數據與資訊，並進行整理摘要。\n"
                "【重要規則】\n"
                "1. 必須保留『表格/欄位名稱』的脈絡（例如指出是哪個設定檔或資料表查詢出的欄位與數據），避免數據失去上下文。\n"
                "2. 僅保留與問題直接關聯的數據與事實，去除無關的欄位或空值。\n"
                "3. 請勿捏造任何數據或資訊，保持真實客觀。\n"
                "4. 摘要以繁體中文撰寫，保持清晰、客觀。"
            )
        else:
            system_content = (
                "你是一個專業的資料夾摘要助理。請針對使用者的問題，從下方提供的這批參考資料段落中萃取與問題相關的重點資訊，並進行整合摘要。\n"
                "【重要規則】\n"
                "1. 必須去除與問題無關的雜訊與贅字，僅保留與問題有直接關聯的核心內容，使其簡明扼要。\n"
                "2. 為了在後續回答中進行來源引用，【必須保留】原始資料的來源標記格式，例如『[文件名] 段落: #段落編號』，並在整理後的摘要段落旁註記其對應的來源標記。\n"
                "3. 請勿自己捏造、補充任何不在參考資料中的資訊。若這批段落中沒有與問題相關的內容，請直接回覆『無相關內容』，不要做無意義的摘要。\n"
                "4. 摘要以繁體中文撰寫，保持清晰、客觀。"
            )
        
        context_data = "\n---\n".join(b["text"] for b in group)
        user_content = f"【使用者問題】\n{question}\n\n【參考資料】\n{context_data}"
        
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content}
        ]

    @classmethod
    def _build_reduce_prompt(cls, question: str, blocks: list[dict], is_db: bool) -> list[dict]:
        """
        建構 Reduce 合併階段的 Prompt。
        """
        if is_db:
            system_content = (
                "你是一個專業的資料庫查詢結果整合助手。請將下方多份分批整理出來的資料庫查詢結果，"
                "合併整合成一份結構完整、條理清晰的最終參考資料。\n"
                "【重要規則】\n"
                "1. 必須保留所有重要的數據、表格及欄位脈絡。\n"
                "2. 去除重複的內容或贅述，重新排版使其易於閱讀。\n"
                "3. 請勿捏造任何資料或數據。\n"
                "4. 最終整合內容以繁體中文呈現。"
            )
        else:
            system_content = (
                "你是一個專業的資料整合助理。請將下方多份分批整理出來的參考資料摘要，"
                "合併整合成一份結構完整、條理清晰的最終參考資料。\n"
                "【重要規則】\n"
                "1. 必須保留所有的來源文件標記（例如『[文件名] 段落: #段落編號』），確保每一筆事實或結論旁都有正確的來源標記註記。\n"
                "2. 去除重複的資訊，將相似的主題進行歸納合併，使其結構分明。\n"
                "3. 請勿自己捏造任何資訊。\n"
                "4. 最終整合內容以繁體中文呈現。"
            )
        
        context_data = "\n---\n".join(b["text"] for b in blocks)
        user_content = f"【使用者問題】\n{question}\n\n【分批摘要內容】\n{context_data}"
        
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content}
        ]

    @classmethod
    async def maybe_summarize(
        cls,
        question: str,
        blocks: list[dict],       # 每個 dict: {"text": str, "label": str}
        threshold_tokens: int,
        result: dict,             # 寫入 result["context_str"] / result["was_summarized"]
        round_no: int = 1,
        is_db: bool = False,
    ):
        """
        主入口：判斷是否需要進行分批摘要，並遞迴執行 Map-Reduce。
        """
        result["rounds"] = round_no
        total = sum(count_tokens(b["text"]) for b in blocks)
        if total <= threshold_tokens:
            if round_no == 1:
                # 初始 token 數未超標，直接合併，不需摘要
                result["context_str"] = "\n---\n".join(b["text"] for b in blocks)
                result["was_summarized"] = False
                return
            else:
                # 已經過摘要（round_no > 1），且目前總 token 數已低於 threshold。
                if len(blocks) == 1:
                    result["context_str"] = blocks[0]["text"]
                    result["was_summarized"] = True
                    return
                else:
                    # 多個分批摘要，呼叫一次 LLM 合併成單一最終上下文
                    reduce_step_key = f"context_summarize_r{round_no}_reduce"
                    label = f"第 {round_no} 輪・合併最終摘要"
                    event_data = {
                        "step": reduce_step_key,
                        "status": "running",
                        "content": f"{label}...",
                        "label": label
                    }
                    yield f"event: step\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                    
                    merged_text = await LLMService.chat_completion(
                        messages=cls._build_reduce_prompt(question, blocks, is_db),
                        temperature=0.2,
                        max_tokens=2048,
                    )
                    result["context_str"] = merged_text
                    result["was_summarized"] = True
                    
                    event_data = {
                        "step": reduce_step_key,
                        "status": "success",
                        "content": f"{label}完成：\n\n{merged_text}",
                        "label": label
                    }
                    yield f"event: step\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                    return

        # Token 數超過 threshold，執行 Map 階段
        groups = cls._bin_pack(blocks, threshold_tokens)
        result["batch_count"] = result.get("batch_count", 0) + len(groups)

        summaries = []
        for i, group in enumerate(groups, start=1):
            step_key = f"context_summarize_r{round_no}_batch_{i}"
            group_tokens = sum(count_tokens(b["text"]) for b in group)
            label = f"第 {round_no} 輪・分批整理 {i}/{len(groups)}（{len(group)} 個區塊，約 {group_tokens} tokens）"
            
            # 組裝原始內容的預覽，供前端展開查看
            raw_preview = "\n---\n".join(b["text"] for b in group)
            event_data = {
                "step": step_key,
                "status": "running",
                "content": f"{label}\n\n原始內容：\n{raw_preview}",
                "label": label
            }
            yield f"event: step\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
            
            try:
                summary_text = await LLMService.chat_completion(
                    messages=cls._build_map_prompt(question, group, is_db),
                    temperature=0.2,
                    max_tokens=1500,
                )
                summaries.append({"text": summary_text, "label": f"摘要（第 {round_no} 輪批次 {i}）"})
                event_data = {
                    "step": step_key,
                    "status": "success",
                    "content": f"{label}\n\n整理結果：\n{summary_text}",
                    "label": label
                }
                yield f"event: step\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error(f"Error in context summarization at round {round_no} batch {i}: {e}")
                event_data = {
                    "step": step_key,
                    "status": "failed",
                    "content": f"{label}失敗：{str(e)}",
                    "label": label
                }
                yield f"event: step\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                raise e

        # 檢查是否達到最大遞迴輪數
        if round_no >= settings.CONTEXT_SUMMARIZE_MAX_ROUNDS:
            note = f"【系統提示】已達分批摘要輪數上限（{settings.CONTEXT_SUMMARIZE_MAX_ROUNDS} 輪），直接合併摘要結果。"
            result["context_str"] = note + "\n\n" + "\n---\n".join(s["text"] for s in summaries)
            result["was_summarized"] = True
            
            final_step_key = f"context_summarize_r{round_no}_reduce"
            event_data = {
                "step": final_step_key,
                "status": "success",
                "content": f"已達最大輪數，直接合併摘要結果。\n\n" + result["context_str"],
                "label": f"第 {round_no} 輪・合併最終摘要"
            }
            yield f"event: step\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
            return

        if len(summaries) == 1:
            result["context_str"] = summaries[0]["text"]
            result["was_summarized"] = True
            return

        # 進入 Reduce 階段：遞迴合併
        reduce_step_key = f"context_summarize_r{round_no}_reduce"
        event_data = {
            "step": reduce_step_key,
            "status": "running",
            "content": f"正在將 {len(summaries)} 份摘要整合成一份最終上下文...",
            "label": f"第 {round_no} 輪・合併最終摘要"
        }
        yield f"event: step\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
        
        async for evt in cls.maybe_summarize(
            question=question,
            blocks=summaries,
            threshold_tokens=threshold_tokens,
            result=result,
            round_no=round_no + 1,
            is_db=is_db
        ):
            yield evt

        event_data = {
            "step": reduce_step_key,
            "status": "success",
            "content": f"已將 {len(summaries)} 份摘要整合完成，交由下一輪繼續處理。",
            "label": f"第 {round_no} 輪・合併最終摘要"
        }
        yield f"event: step\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
