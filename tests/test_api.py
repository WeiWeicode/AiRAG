import urllib.request
import urllib.parse
import json
import time
import os
import uuid
import mimetypes

BASE_URL = "http://10.10.130.45:53020"
# python tests/test_api.py
class APITestRunner:
    def __init__(self, base_url):
        self.base_url = base_url
        self.token = None
        self.kb_id = None
        self.results = []
        self.file_content_to_test = "這是測試 AiRAG 平台的測試文本。我們希望能夠完整切分、向量化並寫入知識庫。這是第二段內容，主要用來測試 overlap 重疊區間的效果。"

    def run_request(self, method, path, data=None, headers=None, is_json=True, multipart_files=None):
        url = f"{self.base_url}{path}"
        if headers is None:
            headers = {}
        
        # Add Authorization token if present
        if self.token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self.token}"

        req_data = None
        if multipart_files:
            # Construct Multipart body
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
            CRLF = b"\r\n"
            parts = []
            for field_name, filename, value in multipart_files:
                parts.append(f"--{boundary}".encode('utf-8'))
                parts.append(f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'.encode('utf-8'))
                content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                parts.append(f'Content-Type: {content_type}'.encode('utf-8'))
                parts.append(b"")
                if isinstance(value, str):
                    value = value.encode('utf-8')
                parts.append(value)
            parts.append(f"--{boundary}--".encode('utf-8'))
            parts.append(b"")
            req_data = CRLF.join(parts)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif data is not None:
            if is_json:
                req_data = json.dumps(data).encode('utf-8')
                headers["Content-Type"] = "application/json"
            else:
                req_data = urllib.parse.urlencode(data).encode('utf-8')
                headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
        
        start_time = time.time()
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                status_code = response.getcode()
                response_body = response.read().decode('utf-8')
                elapsed = int((time.time() - start_time) * 1000)
                try:
                    parsed_json = json.loads(response_body)
                except ValueError:
                    parsed_json = response_body
                return status_code, parsed_json, elapsed
        except urllib.error.HTTPError as e:
            elapsed = int((time.time() - start_time) * 1000)
            try:
                error_body = e.read().decode('utf-8')
                parsed_json = json.loads(error_body)
            except Exception:
                parsed_json = str(e)
            return e.code, parsed_json, elapsed
        except Exception as e:
            elapsed = int((time.time() - start_time) * 1000)
            return 500, {"error": str(e)}, elapsed

    def add_result(self, test_name, method, path, expected_status, actual_status, elapsed, passed, details=None):
        self.results.append({
            "test_name": test_name,
            "method": method,
            "path": path,
            "expected_status": expected_status,
            "actual_status": actual_status,
            "elapsed_ms": elapsed,
            "passed": passed,
            "details": details
        })
        status_str = "SUCCESS" if passed else "FAILED"
        print(f"[{status_str}] {test_name} ({method} {path}) - {elapsed}ms (Expected: {expected_status}, Got: {actual_status})")

    def run_tests(self):
        print(f"=== Starting AiRAG API Testing against {self.base_url} ===")
        
        # 1. Health Check
        status, res, elapsed = self.run_request("GET", "/health")
        passed = (status == 200 and res.get("status") == "healthy")
        self.add_result("Health Check", "GET", "/health", 200, status, elapsed, passed, res)

        # 2. Login Failure
        status, res, elapsed = self.run_request("POST", "/api/auth/login", {"username": "admin", "password": "wrongpassword"})
        passed = (status == 401)
        self.add_result("Auth Login (Failure Test)", "POST", "/api/auth/login", 401, status, elapsed, passed, res)

        # 3. Login Success
        status, res, elapsed = self.run_request("POST", "/api/auth/login", {"username": "admin", "password": "admin"})
        passed = (status == 200 and "access_token" in res)
        if passed:
            self.token = res["access_token"]
        self.add_result("Auth Login (Success Test)", "POST", "/api/auth/login", 200, status, elapsed, passed, res)

        # 4. Unauthorized Access Block
        # Create a runner without token
        temp_runner = APITestRunner(self.base_url)
        status, res, elapsed = temp_runner.run_request("GET", "/api/knowledge-bases")
        passed = (status == 401)
        self.add_result("Unauthorized Request Interception", "GET", "/api/knowledge-bases", 401, status, elapsed, passed, res)

        if not self.token:
            print("[CRITICAL] Auth Token not acquired. Skipping authenticated API tests.")
            self.generate_report()
            return

        # 5. Create Knowledge Base
        kb_name = f"TestKB_{uuid.uuid4().hex[:6]}"
        status, res, elapsed = self.run_request("POST", "/api/knowledge-bases", {
            "name": kb_name,
            "description": "Integration Test KB"
        })
        passed = (status == 201 and "id" in res)
        if passed:
            self.kb_id = res["id"]
        self.add_result("Create Knowledge Base", "POST", "/api/knowledge-bases", 201, status, elapsed, passed, res)

        if not self.kb_id:
            print("[CRITICAL] Knowledge Base creation failed. Skipping dependant tests.")
            return

        # 6. List Knowledge Bases
        status, res, elapsed = self.run_request("GET", "/api/knowledge-bases")
        passed = (status == 200 and "items" in res and any(item["id"] == self.kb_id for item in res["items"]))
        self.add_result("List Knowledge Bases", "GET", "/api/knowledge-bases", 200, status, elapsed, passed, res)

        # 6a. SQL Server Articles List
        status, res, elapsed = self.run_request("GET", "/api/sqlserver/articles")
        passed = (status == 200 and "items" in res)
        self.add_result("SQL Server List Articles", "GET", "/api/sqlserver/articles", 200, status, elapsed, passed, res)
        
        article_id_to_import = None
        if passed and res.get("items"):
            article_id_to_import = res["items"][0]["id"]
            
        # 6b. SQL Server Article Import
        if article_id_to_import:
            status, res, elapsed = self.run_request("POST", "/api/sqlserver/import", {
                "article_id": article_id_to_import,
                "knowledge_base_id": self.kb_id,
                "chunk_size": 256,
                "chunk_overlap": 20
            })
            passed = (status == 200 and res.get("inserted_count", 0) > 0)
            self.add_result("SQL Server Import Article", "POST", "/api/sqlserver/import", 200, status, elapsed, passed, res)
        else:
            self.add_result("SQL Server Import Article", "POST", "/api/sqlserver/import", 200, "Skipped", 0, False, "No articles found in SQL Server or connection skipped")

        # 7. Document Upload & Parse
        multipart_data = [("file", "test_doc.txt", self.file_content_to_test)]
        status, res, elapsed = self.run_request("POST", "/api/embedding/upload", multipart_files=multipart_data)
        passed = (status == 200 and "content" in res and "file_id" in res)
        file_id = res.get("file_id") if passed else None
        parsed_content = res.get("content") if passed else None
        self.add_result("Upload & Parse Document", "POST", "/api/embedding/upload", 200, status, elapsed, passed, res)

        # 8. Document Chunking
        if parsed_content:
            status, res, elapsed = self.run_request("POST", "/api/embedding/chunk", {
                "file_id": file_id or str(uuid.uuid4()),
                "content": parsed_content,
                "params": {
                    "chunk_size": 200,
                    "chunk_overlap": 20,
                    "separator": "\n\n"
                }
            })
            passed = (status == 200 and "chunks" in res and len(res["chunks"]) > 0)
            chunks = res.get("chunks") if passed else None
            self.add_result("Chunk Document Content", "POST", "/api/embedding/chunk", 200, status, elapsed, passed, res)
        else:
            chunks = None
            self.add_result("Chunk Document Content", "POST", "/api/embedding/chunk", 200, "Skipped", 0, False, "No parsed content available")

        # 9. Vectorize & Ingestion
        if chunks:
            # Adapt metadata for vectorize format
            vectorize_chunks = []
            for c in chunks:
                vectorize_chunks.append({
                    "index": c["index"],
                    "content": c["content"],
                    "metadata": {
                        "filename": "test_doc.txt",
                        "page": 1,
                        "source": "upload"
                    }
                })
            status, res, elapsed = self.run_request("POST", "/api/embedding/vectorize", {
                "chunks": vectorize_chunks,
                "knowledge_base_id": self.kb_id,
                "embedding_model": "Qwen3-Embedding-8B-Q8_0.gguf"
            })
            passed = (status == 200 and res.get("inserted_count", 0) > 0)
            self.add_result("Vectorize & Ingest to Qdrant", "POST", "/api/embedding/vectorize", 200, status, elapsed, passed, res)
        else:
            self.add_result("Vectorize & Ingest to Qdrant", "POST", "/api/embedding/vectorize", 200, "Skipped", 0, False, "No chunks available")

        # 10. RAG Chat Stub
        status, res, elapsed = self.run_request("POST", "/api/rag/chat", {
            "question": "什麼是 AiRAG?",
            "knowledge_base_id": self.kb_id
        })
        passed = (status == 200)
        self.add_result("RAG Chat Endpoint (Stub)", "POST", "/api/rag/chat", 200, status, elapsed, passed, res)

        # 11. RAG History Stub
        status, res, elapsed = self.run_request("GET", "/api/rag/history")
        passed = (status == 200 and "items" in res)
        self.add_result("RAG Chat History (Stub)", "GET", "/api/rag/history", 200, status, elapsed, passed, res)

        # 12. Retrieval Search Stub
        status, res, elapsed = self.run_request("POST", "/api/retrieval/search", {
            "query": "測試",
            "knowledge_base_id": self.kb_id
        })
        passed = (status == 200)
        self.add_result("Vector Retrieval Search (Stub)", "POST", "/api/retrieval/search", 200, status, elapsed, passed, res)

        # 13. Retrieval Query Transform Stub
        status, res, elapsed = self.run_request("POST", "/api/retrieval/query-transform", {
            "query": "測試",
            "strategy": "rewrite",
            "knowledge_base_id": self.kb_id
        })
        passed = (status == 200)
        self.add_result("Query Transform Search (Stub)", "POST", "/api/retrieval/query-transform", 200, status, elapsed, passed, res)

        # 14. Delete Knowledge Base (Clean up)
        status, res, elapsed = self.run_request("DELETE", f"/api/knowledge-bases/{self.kb_id}")
        passed = (status == 200)
        self.add_result("Delete Knowledge Base (Cleanup)", "DELETE", f"/api/knowledge-bases/{self.kb_id}", 200, status, elapsed, passed, res)

        self.generate_report()

    def generate_report(self):
        report_path = os.path.join(os.path.dirname(__file__), "test_report.md")
        passed_count = sum(1 for r in self.results if r["passed"])
        total_count = len(self.results)
        pass_ratio = (passed_count / total_count) * 100 if total_count > 0 else 0

        markdown = []
        markdown.append("# AiRAG API 測試執行報告")
        markdown.append(f"* **測試主機**: `{self.base_url}`")
        markdown.append(f"* **測試時間**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}")
        markdown.append(f"* **測試統計**: 通過率 **{pass_ratio:.1f}%** ({passed_count} / {total_count})")
        markdown.append("")
        markdown.append("## 1. 測試結果總覽")
        markdown.append("")
        markdown.append("| 測試項目 | 方法 | API 路徑 | 預期狀態 | 實際狀態 | 反應時間 | 結果 |")
        markdown.append("| :--- | :---: | :--- | :---: | :---: | :---: | :---: |")
        
        for r in self.results:
            status_icon = "✅ Passed" if r["passed"] else "❌ Failed"
            markdown.append(f"| {r['test_name']} | `{r['method']}` | `{r['path']}` | {r['expected_status']} | {r['actual_status']} | {r['elapsed_ms']}ms | {status_icon} |")
        
        markdown.append("")
        markdown.append("## 2. 各端點詳細響應內容")
        markdown.append("")

        for r in self.results:
            markdown.append(f"### {r['test_name']} (`{r['method']} {r['path']}`)")
            markdown.append(f"* 狀態碼: `{r['actual_status']}` (預期: `{r['expected_status']}`)")
            markdown.append(f"* 耗時: `{r['elapsed_ms']}ms` ")
            markdown.append(f"* 結果: {'**通過**' if r['passed'] else '**不通過**'}")
            markdown.append("")
            markdown.append("```json")
            markdown.append(json.dumps(r["details"], ensure_ascii=False, indent=2))
            markdown.append("```")
            markdown.append("")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(markdown))
        print(f"\n[INFO] Test report successfully written to {report_path}")

if __name__ == "__main__":
    runner = APITestRunner(BASE_URL)
    runner.run_tests()
