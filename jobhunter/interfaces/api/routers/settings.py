from typing import Any

from fastapi import APIRouter, Depends

from ....application import settings
from ..auth import current_user
from ..deps import get_ctx
from ..schemas import CompanyIn, UrlIn

router = APIRouter(tags=["settings"], dependencies=[Depends(current_user)])


@router.get("/settings")
def get_settings(ctx=Depends(get_ctx)):
    return settings.get(ctx)


@router.put("/settings")
def put_settings(body: dict[str, Any], ctx=Depends(get_ctx)):
    return settings.update(ctx, body)


@router.post("/companies/detect")
def detect(body: UrlIn, ctx=Depends(get_ctx)):
    return settings.detect(ctx, body.url)


@router.get("/companies")
def list_companies(ctx=Depends(get_ctx)):
    return ctx.repos.companies.list()


@router.post("/companies")
def add_company(body: CompanyIn, ctx=Depends(get_ctx)):
    return settings.add_company(ctx, **body.model_dump())


@router.patch("/companies/{company_id}")
def patch_company(company_id: int, body: dict[str, Any], ctx=Depends(get_ctx)):
    return settings.update_company(ctx, company_id, body)


@router.delete("/companies/{company_id}")
def delete_company(company_id: int, ctx=Depends(get_ctx)):
    ctx.repos.companies.delete(company_id)
    return {"ok": True}
