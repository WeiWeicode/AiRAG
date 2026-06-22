# AiRAG API 測試執行報告
* **測試主機**: `http://10.10.130.45:53020`
* **測試時間**: 2026-06-18 15:10:29
* **測試統計**: 通過率 **100.0%** (16 / 16)

## 1. 測試結果總覽

| 測試項目 | 方法 | API 路徑 | 預期狀態 | 實際狀態 | 反應時間 | 結果 |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: |
| Health Check | `GET` | `/health` | 200 | 200 | 63ms | ✅ Passed |
| Auth Login (Failure Test) | `POST` | `/api/auth/login` | 401 | 401 | 218ms | ✅ Passed |
| Auth Login (Success Test) | `POST` | `/api/auth/login` | 200 | 200 | 195ms | ✅ Passed |
| Unauthorized Request Interception | `GET` | `/api/knowledge-bases` | 401 | 401 | 10ms | ✅ Passed |
| Create Knowledge Base | `POST` | `/api/knowledge-bases` | 201 | 201 | 65ms | ✅ Passed |
| List Knowledge Bases | `GET` | `/api/knowledge-bases` | 200 | 200 | 33ms | ✅ Passed |
| SQL Server List Articles | `GET` | `/api/sqlserver/articles` | 200 | 200 | 31ms | ✅ Passed |
| SQL Server Import Article | `POST` | `/api/sqlserver/import` | 200 | 200 | 629ms | ✅ Passed |
| Upload & Parse Document | `POST` | `/api/embedding/upload` | 200 | 200 | 16ms | ✅ Passed |
| Chunk Document Content | `POST` | `/api/embedding/chunk` | 200 | 200 | 19ms | ✅ Passed |
| Vectorize & Ingest to Qdrant | `POST` | `/api/embedding/vectorize` | 200 | 200 | 30ms | ✅ Passed |
| RAG Chat Endpoint (Stub) | `POST` | `/api/rag/chat` | 200 | 200 | 16ms | ✅ Passed |
| RAG Chat History (Stub) | `GET` | `/api/rag/history` | 200 | 200 | 15ms | ✅ Passed |
| Vector Retrieval Search (Stub) | `POST` | `/api/retrieval/search` | 200 | 200 | 36ms | ✅ Passed |
| Query Transform Search (Stub) | `POST` | `/api/retrieval/query-transform` | 200 | 200 | 17ms | ✅ Passed |
| Delete Knowledge Base (Cleanup) | `DELETE` | `/api/knowledge-bases/6a3399f4db2e4ae2e469601d` | 200 | 200 | 21ms | ✅ Passed |

## 2. 各端點詳細響應內容

### Health Check (`GET /health`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `63ms` 
* 結果: **通過**

```json
{
  "status": "healthy",
  "service": "AiRAG Testbed API"
}
```

### Auth Login (Failure Test) (`POST /api/auth/login`)
* 狀態碼: `401` (預期: `401`)
* 耗時: `218ms` 
* 結果: **通過**

```json
{
  "detail": "帳號或密碼錯誤"
}
```

### Auth Login (Success Test) (`POST /api/auth/login`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `195ms` 
* 結果: **通過**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTc4MTg1MzA0NH0.Xp2VzKA2oXcNIyFAld6m25ENQnmw_IUX4Pvz70I5DOI",
  "token_type": "bearer",
  "expires_in": 86400
}
```

### Unauthorized Request Interception (`GET /api/knowledge-bases`)
* 狀態碼: `401` (預期: `401`)
* 耗時: `10ms` 
* 結果: **通過**

```json
{
  "detail": "Not authenticated"
}
```

### Create Knowledge Base (`POST /api/knowledge-bases`)
* 狀態碼: `201` (預期: `201`)
* 耗時: `65ms` 
* 結果: **通過**

```json
{
  "id": "6a3399f4db2e4ae2e469601d",
  "name": "TestKB_0881f0",
  "description": "Integration Test KB",
  "chunk_count": 0,
  "created_at": "2026-06-18T07:10:44.710274"
}
```

### List Knowledge Bases (`GET /api/knowledge-bases`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `33ms` 
* 結果: **通過**

```json
{
  "items": [
    {
      "id": "6a3399f4db2e4ae2e469601d",
      "name": "TestKB_0881f0",
      "description": "Integration Test KB",
      "chunk_count": 0,
      "created_at": "2026-06-18T07:10:44.710000"
    }
  ]
}
```

### SQL Server List Articles (`GET /api/sqlserver/articles`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `31ms` 
* 結果: **通過**

```json
{
  "items": [
    {
      "id": "32",
      "title": "知識庫操作說明",
      "is_published": true,
      "is_public": true,
      "access_dept": "",
      "access_members": "\"[]\"",
      "access_level": 10,
      "version_number": 1,
      "created_by": "S112009",
      "created_by_name": "蔣佳緯",
      "created_at": "2026-05-27T08:24:15.359000",
      "updated_at": "2026-05-27T08:24:15.360000"
    },
    {
      "id": "33",
      "title": "EFGP",
      "is_published": true,
      "is_public": false,
      "access_dept": "",
      "access_members": "\"[]\"",
      "access_level": 10,
      "version_number": 1,
      "created_by": "S114013",
      "created_by_name": "蔡倉綺",
      "created_at": "2026-06-16T02:46:47.645000",
      "updated_at": "2026-06-16T02:46:47.646000"
    },
    {
      "id": "34",
      "title": "電子發票設定",
      "is_published": true,
      "is_public": false,
      "access_dept": "",
      "access_members": "\"[]\"",
      "access_level": 10,
      "version_number": 3,
      "created_by": "S094009",
      "created_by_name": "鄭智寬",
      "created_at": "2026-06-16T04:44:20.472000",
      "updated_at": "2026-06-16T05:04:55.984000"
    },
    {
      "id": "35",
      "title": "開帳設定",
      "is_published": true,
      "is_public": false,
      "access_dept": "",
      "access_members": "\"[]\"",
      "access_level": 10,
      "version_number": 3,
      "created_by": "S094009",
      "created_by_name": "鄭智寬",
      "created_at": "2026-06-16T05:09:42.566000",
      "updated_at": "2026-06-16T05:20:32.085000"
    },
    {
      "id": "36",
      "title": "開帳語法",
      "is_published": true,
      "is_public": false,
      "access_dept": "",
      "access_members": "\"[]\"",
      "access_level": 10,
      "version_number": 1,
      "created_by": "S094009",
      "created_by_name": "鄭智寬",
      "created_at": "2026-06-16T05:25:49.102000",
      "updated_at": "2026-06-16T05:25:49.104000"
    },
    {
      "id": "37",
      "title": "apmr900.4gl",
      "is_published": true,
      "is_public": false,
      "access_dept": "",
      "access_members": "\"[]\"",
      "access_level": 10,
      "version_number": 1,
      "created_by": "S114013",
      "created_by_name": "蔡倉綺",
      "created_at": "2026-06-16T07:11:19.825000",
      "updated_at": "2026-06-16T07:11:19.825000"
    },
    {
      "id": "38",
      "title": "採購單列印apmr900",
      "is_published": true,
      "is_public": true,
      "access_dept": "",
      "access_members": "\"[]\"",
      "access_level": 10,
      "version_number": 1,
      "created_by": "S114013",
      "created_by_name": "蔡倉綺",
      "created_at": "2026-06-16T07:16:54.236000",
      "updated_at": "2026-06-16T07:16:54.236000"
    },
    {
      "id": "39",
      "title": "gat_file 檔案名稱多語言對照檔",
      "is_published": true,
      "is_public": true,
      "access_dept": "",
      "access_members": "\"[]\"",
      "access_level": 10,
      "version_number": 1,
      "created_by": "S114013",
      "created_by_name": "蔡倉綺",
      "created_at": "2026-06-17T00:02:14.247000",
      "updated_at": "2026-06-17T00:02:14.248000"
    }
  ],
  "total": 8
}
```

### SQL Server Import Article (`POST /api/sqlserver/import`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `629ms` 
* 結果: **通過**

```json
{
  "knowledge_base_id": "6a3399f4db2e4ae2e469601d",
  "inserted_count": 114,
  "elapsed_ms": 608
}
```

### Upload & Parse Document (`POST /api/embedding/upload`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `16ms` 
* 結果: **通過**

```json
{
  "file_id": "113c652d-1a7d-4b27-95f0-eaa8fa2847db",
  "filename": "test_doc.txt",
  "content": "這是測試 AiRAG 平台的測試文本。我們希望能夠完整切分、向量化並寫入知識庫。這是第二段內容，主要用來測試 overlap 重疊區間的效果。",
  "page_count": 1,
  "char_count": 71
}
```

### Chunk Document Content (`POST /api/embedding/chunk`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `19ms` 
* 結果: **通過**

```json
{
  "chunks": [
    {
      "index": 0,
      "content": "這是測試 AiRAG 平台的測試文本。我們希望能夠完整切分、向量化並寫入知識庫。這是第二段內容，主要用來測試 overlap 重疊區間的效果。",
      "token_count": 49,
      "char_count": 71,
      "start_char": 0,
      "end_char": 71
    }
  ],
  "total_chunks": 1,
  "avg_token_count": 49
}
```

### Vectorize & Ingest to Qdrant (`POST /api/embedding/vectorize`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `30ms` 
* 結果: **通過**

```json
{
  "knowledge_base_id": "6a3399f4db2e4ae2e469601d",
  "inserted_count": 1,
  "embedding_model": "Qwen3-Embedding-8B-Q8_0.gguf",
  "elapsed_ms": 12
}
```

### RAG Chat Endpoint (Stub) (`POST /api/rag/chat`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `16ms` 
* 結果: **通過**

```json
{
  "message": "RAG chat endpoint stub. Implemented in Phase 2."
}
```

### RAG Chat History (Stub) (`GET /api/rag/history`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `15ms` 
* 結果: **通過**

```json
{
  "total": 0,
  "items": []
}
```

### Vector Retrieval Search (Stub) (`POST /api/retrieval/search`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `36ms` 
* 結果: **通過**

```json
{
  "query": "",
  "results": [],
  "elapsed_ms": 0
}
```

### Query Transform Search (Stub) (`POST /api/retrieval/query-transform`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `17ms` 
* 結果: **通過**

```json
{
  "original_query": "",
  "transformed_query": "",
  "strategy": "none",
  "results": []
}
```

### Delete Knowledge Base (Cleanup) (`DELETE /api/knowledge-bases/6a3399f4db2e4ae2e469601d`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `21ms` 
* 結果: **通過**

```json
{
  "message": "刪除成功"
}
```
