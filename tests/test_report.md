# AiRAG API 測試執行報告
* **測試主機**: `http://10.10.130.45:53020`
* **測試時間**: 2026-06-25 14:57:40
* **測試統計**: 通過率 **75.0%** (12 / 16)

## 1. 測試結果總覽

| 測試項目 | 方法 | API 路徑 | 預期狀態 | 實際狀態 | 反應時間 | 結果 |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: |
| Health Check | `GET` | `/health` | 200 | 200 | 57ms | ✅ Passed |
| Auth Login (Failure Test) | `POST` | `/api/auth/login` | 401 | 401 | 208ms | ✅ Passed |
| Auth Login (Success Test) | `POST` | `/api/auth/login` | 200 | 200 | 195ms | ✅ Passed |
| Unauthorized Request Interception | `GET` | `/api/knowledge-bases` | 401 | 401 | 26ms | ✅ Passed |
| Create Knowledge Base | `POST` | `/api/knowledge-bases` | 201 | 201 | 45ms | ✅ Passed |
| List Knowledge Bases | `GET` | `/api/knowledge-bases` | 200 | 200 | 33ms | ✅ Passed |
| SQL Server List Articles | `GET` | `/api/sqlserver/articles` | 200 | 200 | 53ms | ✅ Passed |
| SQL Server Import Article | `POST` | `/api/sqlserver/import` | 200 | 500 | 10040ms | ❌ Failed |
| Upload & Parse Document | `POST` | `/api/embedding/upload` | 200 | 500 | 10002ms | ❌ Failed |
| Chunk Document Content | `POST` | `/api/embedding/chunk` | 200 | Skipped | 0ms | ❌ Failed |
| Vectorize & Ingest to Qdrant | `POST` | `/api/embedding/vectorize` | 200 | Skipped | 0ms | ❌ Failed |
| RAG Chat Endpoint (Stub) | `POST` | `/api/rag/chat` | 200 | 200 | 11233ms | ✅ Passed |
| RAG Chat History (Stub) | `GET` | `/api/rag/history` | 200 | 200 | 34ms | ✅ Passed |
| Vector Retrieval Search (Stub) | `POST` | `/api/retrieval/search` | 200 | 200 | 134ms | ✅ Passed |
| Query Transform Search (Stub) | `POST` | `/api/retrieval/query-transform` | 200 | 200 | 5183ms | ✅ Passed |
| Delete Knowledge Base (Cleanup) | `DELETE` | `/api/knowledge-bases/6a3cd16200ea3769c5d8b221` | 200 | 200 | 44ms | ✅ Passed |

## 2. 各端點詳細響應內容

### Health Check (`GET /health`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `57ms` 
* 結果: **通過**

```json
{
  "status": "healthy",
  "service": "AiRAG Testbed API"
}
```

### Auth Login (Failure Test) (`POST /api/auth/login`)
* 狀態碼: `401` (預期: `401`)
* 耗時: `208ms` 
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
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTc4MjQ1NzA1OH0.CBpGb9GIRmvqHpsri8dvoI6JEbO5FXJKDLLgP7AW428",
  "token_type": "bearer",
  "expires_in": 86400
}
```

### Unauthorized Request Interception (`GET /api/knowledge-bases`)
* 狀態碼: `401` (預期: `401`)
* 耗時: `26ms` 
* 結果: **通過**

```json
{
  "detail": "Not authenticated"
}
```

### Create Knowledge Base (`POST /api/knowledge-bases`)
* 狀態碼: `201` (預期: `201`)
* 耗時: `45ms` 
* 結果: **通過**

```json
{
  "id": "6a3cd16200ea3769c5d8b221",
  "name": "TestKB_706d0a",
  "description": "Integration Test KB",
  "chunk_count": 0,
  "created_at": "2026-06-25T06:57:38.369631"
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
      "id": "6a3b2f3068ad83a7f6753d0b",
      "name": "預設知識庫",
      "description": "系統自動建立的預設知識庫",
      "chunk_count": 1783,
      "created_at": "2026-06-24T01:13:20.468000"
    },
    {
      "id": "6a3cd16200ea3769c5d8b221",
      "name": "TestKB_706d0a",
      "description": "Integration Test KB",
      "chunk_count": 0,
      "created_at": "2026-06-25T06:57:38.369000"
    }
  ]
}
```

### SQL Server List Articles (`GET /api/sqlserver/articles`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `53ms` 
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
* 狀態碼: `500` (預期: `200`)
* 耗時: `10040ms` 
* 結果: **不通過**

```json
{
  "error": "timed out"
}
```

### Upload & Parse Document (`POST /api/embedding/upload`)
* 狀態碼: `500` (預期: `200`)
* 耗時: `10002ms` 
* 結果: **不通過**

```json
{
  "error": "timed out"
}
```

### Chunk Document Content (`POST /api/embedding/chunk`)
* 狀態碼: `Skipped` (預期: `200`)
* 耗時: `0ms` 
* 結果: **不通過**

```json
"No parsed content available"
```

### Vectorize & Ingest to Qdrant (`POST /api/embedding/vectorize`)
* 狀態碼: `Skipped` (預期: `200`)
* 耗時: `0ms` 
* 結果: **不通過**

```json
"No chunks available"
```

### RAG Chat Endpoint (Stub) (`POST /api/rag/chat`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `11233ms` 
* 結果: **通過**

```json
"event: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"Here\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"'s\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" a\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" thinking\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" process\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \":\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"1\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" **\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"An\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"alyze\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" User\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Input\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \":**\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" User\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" asks\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \":\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\\"\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"什麼是\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Ai\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"R\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"AG\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"?\\\"\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" (\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"What\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" is\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Ai\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"R\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"AG\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"?)\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" System\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Prompt\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \":\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\\"\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"你\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"是一個\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"專業的\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" R\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"AG\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"智慧\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"對話\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"助理\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"。\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"由於\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"目前\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"沒有\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"提供任何\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"參考\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"資料\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"，\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"請\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"直接\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"回答\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"『\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"知識\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"庫\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"沒有\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"相關\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"資訊\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"。\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"』\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"，\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"絕對\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"不要\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"回答\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"其他\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"內容\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"。\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\\"\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" (\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"You\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" are\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" a\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" professional\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" R\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"AG\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" intelligent\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" dialogue\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" assistant\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Since\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" no\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" reference\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" materials\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" are\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" provided\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \",\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" please\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" directly\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" answer\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" '\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"知識\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"庫\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"沒有\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"相關\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"資訊\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"。\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"',\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" absolutely\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" do\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" not\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" answer\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" anything\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" else\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".)\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"2\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" **\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"Ident\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"ify\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Key\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Constraints\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \":**\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" I\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" am\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" a\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" R\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"AG\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" assistant\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" No\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" reference\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" materials\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" are\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" provided\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" I\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" must\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" directly\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" answer\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" exactly\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \":\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\\"\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"知識\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"庫\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"沒有\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"相關\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"資訊\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"。\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\\"\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" I\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" must\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" absolutely\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" not\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" answer\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" anything\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" else\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"3\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" **\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"Form\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"ulate\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Response\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \":**\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Check\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" constraint\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \":\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Must\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" be\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" exactly\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\\"\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"知識\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"庫\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"沒有\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"相關\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"資訊\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"。\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\\"\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" No\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" extra\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" text\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \",\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" no\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" explanations\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \",\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" no\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" greetings\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Output\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" matches\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" constraint\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" exactly\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"4\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" **\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"Final\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Output\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Generation\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \":**\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\\"\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"知識\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"庫\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"沒有\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"相關\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"資訊\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"。\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\\"\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" (\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"Matches\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" exactly\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \")\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"✅\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Proceed\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Self\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"-C\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"or\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"rection\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"/\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"Verification\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" during\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" thought\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \":\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" The\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" prompt\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" is\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" very\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" strict\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" I\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" will\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" output\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" exactly\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" that\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" phrase\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" No\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" extra\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" characters\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" All\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" good\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Output\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" matches\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" requirement\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"✅\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Proceed\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"s\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" [\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"Output\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Generation\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"]\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" ->\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"知識\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"庫\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"沒有\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"相關\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"資訊\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"。\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Done\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" *\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"Self\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"-C\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"or\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"rection\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"/\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"Note\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" during\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" thought\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"*:\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Wait\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \",\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" the\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" prompt\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" says\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\\"\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"由於\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"目前\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"沒有\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"提供任何\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"參考\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"資料\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"，\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"請\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"直接\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"回答\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"『\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"知識\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"庫\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"沒有\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"相關\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"資訊\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"。\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"』\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"，\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"絕對\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"不要\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"回答\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"其他\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"內容\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"。\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\\"\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" This\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" is\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" a\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" strict\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" instruction\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" I\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" will\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" follow\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" it\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" exactly\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" No\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" extra\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" words\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" All\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" good\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Output\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \":\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"知識\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"庫\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"沒有\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"相關\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"資訊\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"。\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Done\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" [\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"Final\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Check\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"]\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Matches\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" constraint\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" perfectly\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Proceed\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"s\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" [\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"Output\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" Generation\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"]\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" ->\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"知識\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"庫\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"沒有\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"相關\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"資訊\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"。\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" (\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"Note\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \":\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" I\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" will\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" output\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" exactly\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" that\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" string\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".)\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" \\n\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"  \"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" -\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" All\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" steps\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \" verified\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \".\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"✅\"}\n\nevent: chunk\ndata: {\"type\": \"reasoning\", \"content\": \"\\n\"}\n\nevent: chunk\ndata: {\"type\": \"content\", \"content\": \"\\n\\n\"}\n\nevent: chunk\ndata: {\"type\": \"content\", \"content\": \"知識\"}\n\nevent: chunk\ndata: {\"type\": \"content\", \"content\": \"庫\"}\n\nevent: chunk\ndata: {\"type\": \"content\", \"content\": \"沒有\"}\n\nevent: chunk\ndata: {\"type\": \"content\", \"content\": \"相關\"}\n\nevent: chunk\ndata: {\"type\": \"content\", \"content\": \"資訊\"}\n\nevent: chunk\ndata: {\"type\": \"content\", \"content\": \"。\"}\n\nevent: sources\ndata: {\"sources\": []}\n\nevent: chunk\ndata: {\"type\": \"done\"}\n\n"
```

### RAG Chat History (Stub) (`GET /api/rag/history`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `34ms` 
* 結果: **通過**

```json
{
  "total": 0,
  "items": []
}
```

### Vector Retrieval Search (Stub) (`POST /api/retrieval/search`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `134ms` 
* 結果: **通過**

```json
{
  "query": "測試",
  "results": [
    {
      "chunk_id": "82c70d71-75fc-43b7-89fd-6825dc77cfff",
      "content": "，幫助同仁核對資訊。                                                                                                |",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 72,
        "tags": []
      },
      "score": 0.73998356,
      "distance": 0.26001644
    },
    {
      "chunk_id": "459ddb8a-cff6-41f3-8118-16003b77e8af",
      "content": " |",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 23,
        "tags": []
      },
      "score": 0.704578,
      "distance": 0.29542199999999996
    },
    {
      "chunk_id": "8529bf44-cb12-4581-8686-9a790fd11b98",
      "content": "標定，大幅提升檢索精準度。                                                                                              |",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 112,
        "tags": []
      },
      "score": 0.6971009,
      "distance": 0.3028991
    },
    {
      "chunk_id": "239d99fc-3108-4a09-8a17-1b7587d9c813",
      "content": "## 三、 首頁功能說明\n\n首頁是同仁每天的工作大廳，提供了全系統的**快速檢索引擎**與**個人通知中心**。\n\n### 3.1 知識檢索與標籤篩選\n\n檢索引擎採用即時模糊搜尋技術，可以同時對知識庫內的所有「文章標題/內文」與「附件檔名/說明」進行全方位檢索。",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 24,
        "tags": []
      },
      "score": 0.6709149,
      "distance": 0.3290851
    },
    {
      "chunk_id": "ba2cc69c-eee8-4510-beeb-2138b3d57330",
      "content": "### 1.2 登入頁按鈕與欄位說明",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 2,
        "tags": []
      },
      "score": 0.6704367,
      "distance": 0.3295633
    },
    {
      "chunk_id": "0db176d9-2298-40ae-942e-b26eaec7ff6c",
      "content": "### 2.2 最左側主選單按鈕與欄位說明\n\n主選單提供全域的檢視模式切換與頁面跳轉連結。",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 14,
        "tags": []
      },
      "score": 0.66783327,
      "distance": 0.33216672999999997
    },
    {
      "chunk_id": "8015b15d-ad5e-4ba5-b985-d7c111de3021",
      "content": "### 未來的 AI 模組規劃預覽：",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 107,
        "tags": []
      },
      "score": 0.66429216,
      "distance": 0.33570784
    },
    {
      "chunk_id": "a5caa985-d166-41ba-a709-68cf8c464dfe",
      "content": "天內已被讀取的歷史提及通知，作為工作紀錄備查。                                           |",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 34,
        "tags": []
      },
      "score": 0.65987074,
      "distance": 0.34012926
    }
  ],
  "elapsed_ms": 105
}
```

### Query Transform Search (Stub) (`POST /api/retrieval/query-transform`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `5183ms` 
* 結果: **通過**

```json
{
  "original_query": "測試",
  "transformed_query": "Here's a thinking process:\n\n1.  **Analyze User Input:**\n   - **Role:** Search Retrieval Optimization Expert (搜尋檢索優化專家)\n   - **Task:** Rewrite the user's query into keywords or a question sentence better suited for vector search (semantic retrieval).\n   - **Rules:** Output ONLY the rewritten content. NO leading words, explanations, descriptions, or punctuation marks.\n   - **Original Query:** 測試 (Test)\n\n2.  **Identify Key Constraints & Challenges:**\n   - The original query \"測試\" is extremely vague and generic. It's literally just \"test\".\n   - Vector search relies on semantic meaning. A single word like \"test\" lacks context.\n   - I need to transform it into something that captures the *intent* of testing in a search/retrieval context, or expand it into a more descriptive, semantically rich phrase/question that would work well in a vector database.\n   - However, I must strictly follow the rule: \"請只輸出重寫後的內容，不要有任何前導詞、說明、解釋或標點符號。\" (Only output the rewritten content, no leading words, explanations, descriptions, or punctuation marks.)",
  "strategy": "rewrite",
  "results": [
    {
      "chunk_id": "8529bf44-cb12-4581-8686-9a790fd11b98",
      "content": "標定，大幅提升檢索精準度。                                                                                              |",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 112,
        "tags": []
      },
      "score": 0.6880139,
      "distance": 0.31198610000000004
    },
    {
      "chunk_id": "0c06cf86-50db-4b90-ad35-5bdc55cfefa8",
      "content": "---------------------- |\n| **AI 智慧問答大廳 (AiChatPanel)**      | 首頁 / 右側快捷懸浮面板 | 提供同仁直接向 AI 助手發問，AI 將自動檢索知識庫中的公開及有權限的部門文章，進行可信賴的語意問答與資料整理。                                                                                |\n| **AI 智慧寫作輔助 (Correct/Generate)** | 文章",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 110,
        "tags": []
      },
      "score": 0.68240523,
      "distance": 0.31759477
    },
    {
      "chunk_id": "520a4c62-25d4-4d2a-b193-c0ceed7b7196",
      "content": "--------------------------------------------------------------------- |\n| **搜尋輸入框**           | 關鍵字輸入 (Search)  | 輸入欲查詢之關鍵字。系統會在您停止輸入後的 300 毫秒後，自動觸發即時搜尋。                                                                                                       ",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 27,
        "tags": []
      },
      "score": 0.675589,
      "distance": 0.324411
    },
    {
      "chunk_id": "1519e548-51b9-4cb1-b500-c4bf1fd23083",
      "content": "## 九、 AI 智慧輔助功能說明\n\n為了提升集團同仁的文件撰寫效率與知識檢索體驗，系統在設計時已規劃了豐富的 AI 智慧模組：\n\n> **🛑 重要公告：AI 智慧輔助功能「尚未啟用」**\n> 請所有同仁與主管注意，目前系統中的所有 **AI 智慧輔助功能（包括但不限於首頁 AI 問答面版、文章編輯頁的 AI 輔助產生文章/校正文章、AI 全域關鍵字自動標籤等）目前均標示為「尚未啟用 / 建置中」**。相關後台 Ollama 引擎與後端 AI API 端點正在積極進行系統對接與設備採購評估中。",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 106,
        "tags": []
      },
      "score": 0.64581877,
      "distance": 0.35418123
    },
    {
      "chunk_id": "020a1110-3b34-428c-b2c3-d93e29fdf7a3",
      "content": "ect/Generate)** | 文章新建與編輯介面      | 在建立文章時自動生成 Markdown 大綱或內文；在編輯文章時自動進行錯字校正、語句修飾與格式排版。<br>**套用機制：**提供「套用」與「捨棄」按鈕，同仁可一鍵將 AI 預覽內容覆寫入 Vditor 編輯器中。 |\n| **AI 標籤自動指派**                    | 文章/附件標籤管理       | AI 將根據文章與附件的內容，自動分析並推薦最合適的關鍵字標籤進行一鍵標定，大幅提升檢索精準度。       ",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 111,
        "tags": []
      },
      "score": 0.63959706,
      "distance": 0.36040293999999995
    },
    {
      "chunk_id": "239d99fc-3108-4a09-8a17-1b7587d9c813",
      "content": "## 三、 首頁功能說明\n\n首頁是同仁每天的工作大廳，提供了全系統的**快速檢索引擎**與**個人通知中心**。\n\n### 3.1 知識檢索與標籤篩選\n\n檢索引擎採用即時模糊搜尋技術，可以同時對知識庫內的所有「文章標題/內文」與「附件檔名/說明」進行全方位檢索。",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 24,
        "tags": []
      },
      "score": 0.6302079,
      "distance": 0.36979209999999996
    },
    {
      "chunk_id": "ba2cc69c-eee8-4510-beeb-2138b3d57330",
      "content": "### 1.2 登入頁按鈕與欄位說明",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 2,
        "tags": []
      },
      "score": 0.6279902,
      "distance": 0.37200979999999995
    },
    {
      "chunk_id": "dceb9e85-4915-4c1b-820c-f70f6fcf284c",
      "content": "------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |\n| `評論` (底端/右上方)     | 抽屜面板切換按鈕",
      "metadata": {
        "filename": "SQLServer_Article_32",
        "page": 1,
        "section": "知識庫操作說明",
        "chunk_index": 45,
        "tags": []
      },
      "score": 0.62440205,
      "distance": 0.37559794999999996
    }
  ]
}
```

### Delete Knowledge Base (Cleanup) (`DELETE /api/knowledge-bases/6a3cd16200ea3769c5d8b221`)
* 狀態碼: `200` (預期: `200`)
* 耗時: `44ms` 
* 結果: **通過**

```json
{
  "message": "刪除成功"
}
```
