import bcrypt
import jwt
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple
from config import settings

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    驗證明文密碼是否與雜湊密碼相符。
    """
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    """
    將密碼進行 Bcrypt 雜湊。
    """
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    建立 JWT Access Token。
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[dict]:
    """
    解密與驗證 JWT Token，失敗則回傳 None。
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """
    FastAPI 依賴注入：驗證 Token 並取得當前使用者名稱。
    """
    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無效或已過期的 Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="無效的認證主體",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


EXTERNAL_API_KEY_PREFIX_LENGTH = 12

def generate_external_api_key() -> Tuple[str, str, str]:
    """
    產生一把新的外部 API 金鑰，回傳 (完整明碼, 前綴, bcrypt hash)。
    明碼只在建立當下回傳一次，資料庫僅存前綴（供索引查找）與 hash，之後無法再次還原明碼。
    """
    plaintext = secrets.token_urlsafe(32)
    prefix = plaintext[:EXTERNAL_API_KEY_PREFIX_LENGTH]
    hashed = get_password_hash(plaintext)
    return plaintext, prefix, hashed

async def verify_external_api_key(x_api_key: str = Header(...)):
    """
    FastAPI 依賴注入：驗證 /api/external/chat 的 X-API-Key 標頭，通過後回傳對應的 ExternalApiKey 文件
    （並更新 last_used_at）。與 get_current_user 的 JWT 登入驗證各自獨立、不共用——
    這裡驗證的是「已授權的外部系統」，不是「已登入的人類使用者」。
    """
    from models.external_api_key import ExternalApiKey

    if not x_api_key or len(x_api_key) < EXTERNAL_API_KEY_PREFIX_LENGTH:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無效的 API Key")

    prefix = x_api_key[:EXTERNAL_API_KEY_PREFIX_LENGTH]
    key_doc = await ExternalApiKey.find_one(ExternalApiKey.key_prefix == prefix)
    if not key_doc or not key_doc.is_active or not verify_password(x_api_key, key_doc.key_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無效或已停用的 API Key")

    key_doc.last_used_at = datetime.utcnow()
    await key_doc.save()
    return key_doc

