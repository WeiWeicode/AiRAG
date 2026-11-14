import logging
from typing import Any, Dict, List

import httpx

from config import settings

logger = logging.getLogger("airag.models")


class ModelDiscoveryService:
    """
    自動偵測本機 Ollama 已下載的模型（GET /api/tags），並在 .env 未指定模型時自動挑選預設值。

    角色與挑選規則：
    - 對話生成模型（VLLM_MODEL）：留空時挑「模型檔案最大」的 completion 模型，回答品質優先。
    - Instruct 語義解析模型（DenseVector_INSTRUCT_MODEL）：留空時挑「模型檔案最小」的 completion 模型，
      它只負責把提問轉成結構化 JSON，速度比品質重要。
    - Embedding 模型（EMBEDDING_MODEL）：不自動挑選。向量維度必須與既有 Qdrant collection 一致，
      換模型等於整個知識庫要重建，因此只檢查是否存在並在缺少時報錯。
    """

    @staticmethod
    def ollama_root_url() -> str:
        """Ollama 原生 API 掛在服務根路徑，需從 OpenAI 相容的 VLLM_BASE_URL 去掉尾端 /v1。"""
        base = settings.VLLM_BASE_URL.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return base.rstrip("/")

    @classmethod
    async def list_models(cls) -> List[Dict[str, Any]]:
        """
        回傳本機 Ollama 所有模型。連不上或回應格式不對時直接拋出例外，由呼叫端決定如何回報，
        不在這裡吞掉錯誤回空清單（空清單會被誤判為「Ollama 正常但沒有模型」）。
        """
        root = cls.ollama_root_url()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{root}/api/tags")
            response.raise_for_status()
            raw_models = response.json()["models"]

            models = []
            for item in raw_models:
                capabilities = item.get("capabilities")
                if capabilities is None:
                    # 舊版 Ollama 的 /api/tags 不帶 capabilities，需逐一查 /api/show
                    show = await client.post(f"{root}/api/show", json={"model": item["name"]})
                    show.raise_for_status()
                    capabilities = show.json().get("capabilities") or []
                details = item.get("details") or {}
                models.append({
                    "name": item["name"],
                    "size": item.get("size", 0),
                    "parameter_size": details.get("parameter_size") or "",
                    "family": details.get("family") or "",
                    "quantization_level": details.get("quantization_level") or "",
                    "capabilities": capabilities,
                    "is_embedding": "embedding" in capabilities,
                    "is_generation": "completion" in capabilities,
                })
        return models

    @classmethod
    async def resolve_default_models(cls) -> None:
        """
        啟動時呼叫：.env 未指定的模型自動從 Ollama 清單挑選，並寫回 settings，
        讓既有讀取 settings.VLLM_MODEL / DENSE_VECTOR_INSTRUCT_MODEL 的程式碼不需改動。
        已指定但未下載的模型只記錯誤不覆蓋——使用者明確指定的值不該被靜默替換。
        """
        try:
            models = await cls.list_models()
        except Exception as e:
            logger.error(
                f"無法連線 Ollama（{cls.ollama_root_url()}）偵測模型，未指定的模型將維持空值，"
                f"對話會失敗直到 Ollama 啟動後重啟服務：{type(e).__name__}: {e!r}"
            )
            return

        names = {m["name"] for m in models}
        # 依實際檔案大小排序；parameter_size 字串部分模型（如 mlx 格式）為空，不可靠
        generation = sorted((m for m in models if m["is_generation"]), key=lambda m: m["size"])

        if not settings.VLLM_MODEL:
            if generation:
                settings.VLLM_MODEL = generation[-1]["name"]
                logger.info(f"自動選用對話生成模型：{settings.VLLM_MODEL}")
            else:
                logger.error("Ollama 中找不到任何 completion 模型，請先 ollama pull 一個對話模型")
        elif settings.VLLM_MODEL not in names:
            logger.error(f"VLLM_MODEL={settings.VLLM_MODEL} 不在 Ollama 已下載清單中：{sorted(names)}")

        if not settings.DENSE_VECTOR_INSTRUCT_MODEL:
            if generation:
                settings.DENSE_VECTOR_INSTRUCT_MODEL = generation[0]["name"]
                logger.info(f"自動選用 Instruct 語義解析模型：{settings.DENSE_VECTOR_INSTRUCT_MODEL}")
        elif settings.DENSE_VECTOR_INSTRUCT_MODEL not in names:
            logger.error(
                f"DenseVector_INSTRUCT_MODEL={settings.DENSE_VECTOR_INSTRUCT_MODEL} "
                f"不在 Ollama 已下載清單中：{sorted(names)}"
            )

        if settings.EMBEDDING_MODEL not in names:
            logger.error(
                f"EMBEDDING_MODEL={settings.EMBEDDING_MODEL} 不在 Ollama 已下載清單中，"
                f"文件向量化與檢索都會失敗，請執行 ollama pull {settings.EMBEDDING_MODEL}"
            )
