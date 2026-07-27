import asyncio
from models.mongodb import init_mongodb
from models.external_api_key import ExternalApiKey
from models.app_registration import AppRegistration
from models.knowledge_base import KnowledgeBase

async def check():
    await init_mongodb()
    keys = await ExternalApiKey.find_all().to_list()
    print("=== External Api Keys ===")
    for k in keys:
        print(f"ID: {k.id}, Name: {k.name}, KeyPrefix: {k.key_prefix}, Scope: {getattr(k, 'scope', 'chat')}, Active: {k.is_active}")

    apps = await AppRegistration.find_all().to_list()
    print("\n=== App Registrations ===")
    for a in apps:
        print(f"AppID: {a.app_id}, Name: {a.display_name}, BaseURL: {a.base_url}, Mode: {a.report_mode}, Active: {a.is_active}")

    kbs = await KnowledgeBase.find_all().to_list()
    print("\n=== Knowledge Bases ===")
    for kb in kbs:
        print(f"KB_ID: {kb.id}, Name: {kb.name}, Collection: {kb.qdrant_collection_name}")

if __name__ == "__main__":
    asyncio.run(check())
