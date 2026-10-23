from fastapi import APIRouter, Depends

from app.auth.deps import TokenData, require_role
from app.enums import Role

router = APIRouter(prefix="/feed", tags=["Feed"])


@router.get("", response_model=list)
def get_feed(
    current_user: TokenData = Depends(require_role(Role.CLIENT)),
) -> list:
    """Блок «Полезное для вас» (зависит от статуса заявки и типа бизнеса).

    В рамках текущего этапа MVP возвращает пустой список 200 OK.
    """
    return []
