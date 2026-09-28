from fastapi import APIRouter, Depends

from ....application import insights
from ..auth import current_user
from ..deps import get_ctx

router = APIRouter(prefix="/insights", tags=["insights"], dependencies=[Depends(current_user)])


@router.get("/skills")
def skills(min_fit: int = 60, ctx=Depends(get_ctx)):
    return insights.skill_gaps(ctx, min_fit=min_fit)
