import asyncio
from models.mongodb import init_mongodb
from models.external_api_key import ExternalApiKey
from models.app_registration import AppRegistration
from utils.security import generate_external_api_key

async def setup():
    await init_mongodb()
    
    # 1. 建立測試 Ingest API Key
    existing_ingest_key = await ExternalApiKey.find_one(ExternalApiKey.name == "TestIngestKey")
    if existing_ingest_key:
        await existing_ingest_key.delete()
        
    plaintext, prefix, hashed = generate_external_api_key()
    api_key_doc = ExternalApiKey(
        name="TestIngestKey",
        key_prefix=prefix,
        key_hash=hashed,
        scope="ingest",
        is_active=True
    )
    await api_key_doc.insert()
    print(f"[CREATED] Ingest API Key 明碼: {plaintext}")
    print(f"[CREATED] Key Prefix: {api_key_doc.key_prefix}, Scope: {api_key_doc.scope}")

    # 2. 建立測試 AppRegistration (bpm_test)
    existing_app = await AppRegistration.find_one(AppRegistration.app_id == "bpm_test")
    if existing_app:
        await existing_app.delete()

    app_reg = AppRegistration(
        app_id="bpm_test",
        display_name="BPM 測試系統",
        base_url="http://localhost:8080",
        content_docs_path_template="/api/v1/rag-sync-content/docs/{id}",
        content_attachment_path_template="/api/v1/rag-sync-content/attachments/{id}",
        report_mode="webhook",
        is_active=True
    )
    await app_reg.insert()
    print(f"[CREATED] AppRegistration: {app_reg.app_id} (Mode: {app_reg.report_mode})")

if __name__ == "__main__":
    asyncio.run(setup())
