from fastapi import APIRouter, HTTPException, status
from schemas.auth import LoginRequest, LoginResponse
from config import settings
from utils.security import verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/login", response_model=LoginResponse)
async def login(credentials: LoginRequest):
    """
    驗證使用者帳密，成功則回傳 JWT Token。
    """
    # 驗證使用者名稱
    if credentials.username != settings.AUTH_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="帳號或密碼錯誤"
        )
    
    # 驗證密碼雜湊
    if not verify_password(credentials.password, settings.AUTH_PASSWORD_HASH):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="帳號或密碼錯誤"
        )
    
    # 簽發 JWT Token
    access_token = create_access_token(data={"sub": credentials.username})
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.JWT_EXPIRE_MINUTES * 60
    )
