import os
from typing import Optional
from dotenv import load_dotenv

# 載入 .env 檔案
load_dotenv()

class Settings:
    # 認證
    AUTH_USERNAME: str = os.getenv("AUTH_USERNAME", "admin")
    AUTH_PASSWORD_HASH: str = os.getenv("AUTH_PASSWORD_HASH", "")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "8f3c7c2b4d8d1e2e3f4a5b6c7d8e9f0a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

    # vLLM
    VLLM_BASE_URL: str = os.getenv("VLLM_BASE_URL", "http://localhost:8080/v1")
    VLLM_MODEL: str = os.getenv("VLLM_MODEL", "Qwen3.6-35B-A3B-FP8")
    # vLLM 部署時的 --max-model-len。設 > 0 時，chat_completion 會在送出前自動裁切 max_tokens，
    # 避免「prompt tokens + max_tokens」超過模型上限被回 400（呼叫端可能帶入很大的 max_tokens）。
    # 設 0 代表停用自動裁切，維持原本行為。
    VLLM_MAX_MODEL_LEN: int = int(os.getenv("VLLM_MAX_MODEL_LEN", "0"))
    # 自動裁切時預留的安全邊際。以 tiktoken (cl100k_base) 估算 prompt token 與模型實際 tokenizer
    # 存在落差，且 chat template 本身也會佔用 token，需留邊際避免剛好卡在上限
    VLLM_CONTEXT_SAFETY_MARGIN: int = int(os.getenv("VLLM_CONTEXT_SAFETY_MARGIN", "1024"))

    # llama.cpp
    LLAMACPP_BASE_URL: str = os.getenv("LLAMACPP_BASE_URL", "http://localhost:8081")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "Qwen3-Embedding-8B-Q8_0.gguf")
    # Embedding 服務的 API 風格："llamacpp"（預設，原生 /embedding）、"ollama"（原生 /api/embeddings）、"openai"（OpenAI 相容 /v1/embeddings，適用 LM Studio）
    EMBEDDING_API_STYLE: str = os.getenv("EMBEDDING_API_STYLE", "llamacpp")

    # llama.cpp (Instruct 語義化)
    DENSE_VECTOR_LLAMACPP_BASE_URL: str = os.getenv("DenseVector_LLAMACPP_BASE_URL", "http://localhost:8082")
    DENSE_VECTOR_INSTRUCT_MODEL: str = os.getenv("DenseVector_INSTRUCT_MODEL", "Qwen3VL-8B-Instruct-Q4_K_M.gguf")

    # Qdrant
    QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
    QDRANT_API_KEY: Optional[str] = os.getenv("QDRANT_API_KEY", None)

    # MongoDB
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    MONGODB_DATABASE: str = os.getenv("MONGODB_DATABASE", "airag")

    # Redis (arq 背景佇列，供多應用 RAG 同步 ingest 任務使用，見 MULTI_APP_RAG_SYNC_PLAN.md 5.1 節第 7 點)
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))

    # SQL Server (唯讀連線字串)
    SQLSERVER_CONNECTION_STRING: str = os.getenv("SQLSERVER_CONNECTION_STRING", "")

    # 預設參數
    DEFAULT_TOP_K: int = int(os.getenv("DEFAULT_TOP_K", "5"))
    DEFAULT_SCORE_THRESHOLD: float = float(os.getenv("DEFAULT_SCORE_THRESHOLD", "0.7"))
    DEFAULT_CHUNK_SIZE: int = int(os.getenv("DEFAULT_CHUNK_SIZE", "512"))
    DEFAULT_CHUNK_OVERLAP: int = int(os.getenv("DEFAULT_CHUNK_OVERLAP", "50"))
    FEEDBACK_BOOST_WEIGHT: float = float(os.getenv("FEEDBACK_BOOST_WEIGHT", "0.2"))
    # 防止地端 LLM 重複輸出同一句話（無限迴圈）
    DEFAULT_REPETITION_PENALTY: float = float(os.getenv("DEFAULT_REPETITION_PENALTY", "1.1"))
    DEFAULT_FREQUENCY_PENALTY: float = float(os.getenv("DEFAULT_FREQUENCY_PENALTY", "0"))

    # 檢索內容分批摘要
    DEFAULT_CONTEXT_SUMMARIZE_THRESHOLD_TOKENS: int = int(os.getenv("DEFAULT_CONTEXT_SUMMARIZE_THRESHOLD_TOKENS", "50000"))
    CONTEXT_SUMMARIZE_MAX_ROUNDS: int = int(os.getenv("CONTEXT_SUMMARIZE_MAX_ROUNDS", "3"))

    # 語義混合附件查詢法附件存放目錄
    FILE_ATTACHMENTS_DIR: str = os.getenv("FILE_ATTACHMENTS_DIR", "FileAttachments")
    FILE_ATTACHMENTS_IMAGE_SUBDIR: str = os.getenv("FILE_ATTACHMENTS_IMAGE_SUBDIR", "image")
    # 圖片描述並行處理的併發數量上限（同時最多幾張圖片一起送給 vLLM 做多模態描述）。
    # 地端單台 vLLM 的吞吐本來就固定，調高不會變快；在統一記憶體機器（DGX GB10，CPU/GPU
    # 共用同一塊記憶體）上還會同時放大多模態前處理的記憶體峰值，曾造成主機假死，故預設為 1
    IMAGE_CAPTION_CONCURRENCY: int = int(os.getenv("IMAGE_CAPTION_CONCURRENCY", "1"))
    # 送多模態模型前的圖片長邊上限（像素），超過就等比例縮小。圖片的解碼與 patch embedding
    # 是 vLLM 行程內的一般 host 配置，不受 --gpu-memory-utilization 約束，高解析度掃描圖的
    # 前處理會直接吃掉作業系統的餘裕。1536px 足以辨識圖表結構與大部分表格文字；
    # 設為 0 或負值可停用縮圖
    IMAGE_CAPTION_MAX_DIMENSION: int = int(os.getenv("IMAGE_CAPTION_MAX_DIMENSION", "1536"))
    # 單張圖片描述的牆鐘時間上限（秒）。串流模式下 httpx timeout 只約束單次讀取，
    # 需要這道上限才能讓整份文件的圖片處理時間可預估，避免拖垮整個 ingest 任務。
    # 【約束】此值必須小於 LLMService.describe_image() 內 chat_completion 的 httpx timeout（300），
    # 否則逾時會改以 httpx.ReadTimeout 型態拋出，使 describe_image_with_retry() 的
    # 「逾時不重試」分流靜默失效、退回重試 IMAGE_CAPTION_MAX_ATTEMPTS 次的舊行為
    IMAGE_CAPTION_TIMEOUT: int = int(os.getenv("IMAGE_CAPTION_TIMEOUT", "180"))
    # 單張圖片描述的最大嘗試次數（含第一次）與每次重試前的等待秒數（等待時間隨次數遞增）。
    # 地端 vLLM 偶發逾時或無限重複迴圈時自動重試，減少寫入「[圖片描述產生失敗]」佔位段落。
    # 注意：逾時（asyncio.TimeoutError）不適用重試，見 describe_image_with_retry()
    IMAGE_CAPTION_MAX_ATTEMPTS: int = int(os.getenv("IMAGE_CAPTION_MAX_ATTEMPTS", "3"))
    IMAGE_CAPTION_RETRY_DELAY: int = int(os.getenv("IMAGE_CAPTION_RETRY_DELAY", "5"))
    # 單張圖片描述的生成長度上限。描述僅供語意檢索使用，且最終仍會被切碎成多個 chunk，
    # 過大的上限只會讓單張圖片的生成時間不可預期（含大量圖片的 PDF 因此整份同步逾時）
    IMAGE_CAPTION_MAX_TOKENS: int = int(os.getenv("IMAGE_CAPTION_MAX_TOKENS", "4096"))
    # PDF 內嵌圖片的過濾門檻：小於此尺寸（像素）或位元組數者視為 logo／裝飾線／圖示，
    # 不送多模態模型描述，避免一份文件的圖片數量被版面元素灌爆
    IMAGE_MIN_WIDTH: int = int(os.getenv("IMAGE_MIN_WIDTH", "100"))
    IMAGE_MIN_HEIGHT: int = int(os.getenv("IMAGE_MIN_HEIGHT", "100"))
    IMAGE_MIN_BYTES: int = int(os.getenv("IMAGE_MIN_BYTES", "8192"))

    # arq ingest 任務的執行時間上限（秒）。arq 預設僅 300 秒，含大量內嵌圖片的
    # Word/PDF 光是圖片描述就會超過而被判定 TimeoutError，需放寬。
    # 最壞情況約 = ceil(圖片數 / IMAGE_CAPTION_CONCURRENCY)
    #              × IMAGE_CAPTION_MAX_ATTEMPTS × IMAGE_CAPTION_TIMEOUT
    INGEST_JOB_TIMEOUT: int = int(os.getenv("INGEST_JOB_TIMEOUT", "7200"))
    # ingest 任務失敗後的最大嘗試次數（含第一次），避免逾時任務反覆重跑消耗 vLLM 資源。
    # 注意：arq 對 TimeoutError 直接判定失敗、不會重試，此值僅對 worker 重啟等
    # CancelledError 情境生效
    INGEST_JOB_MAX_TRIES: int = int(os.getenv("INGEST_JOB_MAX_TRIES", "2"))
    # 圖片描述階段可佔用 INGEST_JOB_TIMEOUT 的比例，超支後剩餘圖片直接降級為描述失敗，
    # 保留餘裕給切分／embedding／Qdrant upsert，確保文件一定寫得進知識庫。
    # 用比例而非絕對秒數，避免有人調整 INGEST_JOB_TIMEOUT 後忘了同步調整預算
    IMAGE_CAPTION_PHASE_BUDGET_RATIO: float = float(os.getenv("IMAGE_CAPTION_PHASE_BUDGET_RATIO", "0.6"))
    # 內部軟性 deadline 的保留秒數：比 arq 的 job_timeout 早這麼多秒主動放棄，
    # 讓逾時以一般 Exception 形式拋出而能回報 failed（arq 強制中止拋的 CancelledError
    # 繼承 BaseException，攔不到，來源應用會永遠停在 processing）
    INGEST_SOFT_DEADLINE_MARGIN: int = int(os.getenv("INGEST_SOFT_DEADLINE_MARGIN", "120"))
    # arq worker 同時執行的任務數上限（arq 預設 10）。圖片描述併發是「每個任務各自」計算的，
    # 不設限時多份文件同步會有 max_jobs × IMAGE_CAPTION_CONCURRENCY 個請求同時打地端 vLLM，
    # 每張都變慢而觸發逾時。設 2 可讓純文字的小文件穿插消化，不被大圖文件完全阻塞
    ARQ_MAX_JOBS: int = int(os.getenv("ARQ_MAX_JOBS", "2"))

    # 語義資料庫查詢法 (Semantic DB Query)
    AI_DB_QUERY_MAX_ROWS: int = int(os.getenv("AI_DB_QUERY_MAX_ROWS", "50"))
    AI_DB_QUERY_MAX_CHARS: int = int(os.getenv("AI_DB_QUERY_MAX_CHARS", "4000"))
    AI_DB_QUERY_PROFILE_SCORE_THRESHOLD: float = float(os.getenv("AI_DB_QUERY_PROFILE_SCORE_THRESHOLD", "0.5"))
    # 不限定知識庫（全域掃描自動選取）模式下，最多同時執行幾個候選設定檔的查詢並合併結果
    AI_DB_QUERY_MAX_PROFILES_PER_QUERY: int = int(os.getenv("AI_DB_QUERY_MAX_PROFILES_PER_QUERY", "3"))

    # 多輪對話指代消解：語義 JSON 轉換階段納入的最近對話則數之後端預設值，
    # 僅在使用者於前端未輸入 history_context_turns（留空）時採用
    SEMANTIC_JSON_HISTORY_TURNS: int = int(os.getenv("SEMANTIC_JSON_HISTORY_TURNS", "3"))

    # 檢索命中分析儀表板
    DASHBOARD_STATS_DEFAULT_PERIOD_DAYS: int = int(os.getenv("DASHBOARD_STATS_DEFAULT_PERIOD_DAYS", "7"))
    RETRIEVAL_STATS_ENABLED: bool = os.getenv("RETRIEVAL_STATS_ENABLED", "True").lower() == "true"

settings = Settings()
