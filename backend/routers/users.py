import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from beanie import PydanticObjectId

from models.department import Department
from models.user_profile import UserProfile, JOB_TITLE_LEVELS
from utils.security import get_current_user

logger = logging.getLogger("airag.routers.users")

router = APIRouter(prefix="/users", tags=["Users & Departments"])


class DepartmentCreateRequest(BaseModel):
    name: str = Field(..., description="部門名稱")
    code: str = Field(..., description="部門代號")


class DepartmentResponse(BaseModel):
    id: str
    name: str
    code: Optional[str] = None


class UserCreateRequest(BaseModel):
    name: str = Field(..., description="姓名")
    department: str = Field(..., description="所屬部門名稱")
    job_title: str = Field(..., description="職級標籤 (一般人員/組長/課長/經理/總經理/自訂)")
    level: Optional[int] = Field(default=10, description="權限等級 (1~10，數字越低機密越高等級越高)")


class UserResponse(BaseModel):
    id: str
    name: str
    department: str
    department_code: Optional[str] = None
    job_title: str
    level: int
    created_at: str


@router.get("/departments", response_model=List[DepartmentResponse])
async def get_departments(current_user: str = Depends(get_current_user)):
    """
    取得所有部門清單
    """
    depts = await Department.find_all().sort("+name").to_list()
    return [DepartmentResponse(id=str(d.id), name=d.name, code=d.code) for d in depts]


@router.post("/departments", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    request: DepartmentCreateRequest,
    current_user: str = Depends(get_current_user)
):
    """
    新增部門名稱與代號
    """
    name = request.name.strip()
    code = request.code.strip()
    if not name:
        raise HTTPException(status_code=400, detail="部門名稱不能為空")
    if not code:
        raise HTTPException(status_code=400, detail="部門代號不能為空")

    existing = await Department.find_one(Department.name == name)
    if existing:
        raise HTTPException(status_code=400, detail=f"部門 '{name}' 已存在")

    existing_code = await Department.find_one(Department.code == code)
    if existing_code:
        raise HTTPException(status_code=400, detail=f"部門代號 '{code}' 已存在")

    dept = Department(name=name, code=code)
    await dept.insert()
    return DepartmentResponse(id=str(dept.id), name=dept.name, code=dept.code)


@router.delete("/departments/{dept_id}")
async def delete_department(
    dept_id: str,
    current_user: str = Depends(get_current_user)
):
    """
    刪除指定部門
    """
    try:
        obj_id = PydanticObjectId(dept_id)
    except Exception:
        raise HTTPException(status_code=400, detail="無效的部門 ID 格式")

    dept = await Department.get(obj_id)
    if not dept:
        raise HTTPException(status_code=404, detail="找不到指定的部門")

    await dept.delete()
    return {"message": f"已成功刪除部門 '{dept.name}'"}


@router.get("", response_model=List[UserResponse])
async def get_users(current_user: str = Depends(get_current_user)):
    """
    取得所有模擬使用者名冊
    """
    users = await UserProfile.find_all().sort("-created_at").to_list()
    return [
        UserResponse(
            id=str(u.id),
            name=u.name,
            department=u.department,
            department_code=u.department_code,
            job_title=u.job_title,
            level=u.level,
            created_at=u.created_at.strftime("%Y-%m-%d %H:%M:%S")
        )
        for u in users
    ]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: UserCreateRequest,
    current_user: str = Depends(get_current_user)
):
    """
    新增模擬使用者
    """
    name = request.name.strip()
    dept_name = request.department.strip()
    job_title = request.job_title.strip()

    if not name:
        raise HTTPException(status_code=400, detail="使用者姓名不能為空")
    if not dept_name:
        raise HTTPException(status_code=400, detail="請選擇所屬部門")

    allowed_titles = set(JOB_TITLE_LEVELS.keys()) | {"自訂"}
    if job_title not in allowed_titles:
        raise HTTPException(status_code=400, detail="不合法的職級分類")

    if job_title == "自訂":
        if request.level is None or not (1 <= request.level <= 10):
            raise HTTPException(status_code=400, detail="自訂職級數字須介於 1~10")
        final_level = request.level
    else:
        final_level = JOB_TITLE_LEVELS[job_title]

    # 從所屬部門連動帶出部門代號，供 PermissionService 的代號比對邏輯使用；
    # 若找不到對應部門（例如手動呼叫 API 帶入未登記的部門名稱），保留 None，
    # 此時 PermissionService 的雙軌比對仍可退回以部門名稱判斷
    dept = await Department.find_one(Department.name == dept_name)
    dept_code = dept.code if dept else None

    user = UserProfile(
        name=name,
        department=dept_name,
        department_code=dept_code,
        job_title=job_title,
        level=final_level
    )
    await user.insert()

    return UserResponse(
        id=str(user.id),
        name=user.name,
        department=user.department,
        department_code=user.department_code,
        job_title=user.job_title,
        level=user.level,
        created_at=user.created_at.strftime("%Y-%m-%d %H:%M:%S")
    )


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    current_user: str = Depends(get_current_user)
):
    """
    刪除指定的模擬使用者
    """
    try:
        obj_id = PydanticObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="無效的使用者 ID 格式")

    user = await UserProfile.get(obj_id)
    if not user:
        raise HTTPException(status_code=404, detail="找不到指定的使用者")

    await user.delete()
    return {"message": f"已成功刪除使用者 '{user.name}'"}
