from fastapi import APIRouter, Depends

from ....application import answers
from ..auth import current_user
from ..deps import get_ctx
from ..schemas import AnswerIn, AnswerPatch

router = APIRouter(tags=["answers"], dependencies=[Depends(current_user)])


@router.get("/jobs/{job_id}/answers")
def list_answers(job_id: int, ctx=Depends(get_ctx)):
    return answers.list_for_job(ctx, job_id)


@router.post("/answers")
def generate(body: AnswerIn, ctx=Depends(get_ctx)):
    row = answers.generate(ctx, body.job_id, body.question, body.max_words, body.tone, body.emphasis)
    return answers.with_evidence_text(ctx, [row], ctx.repos.jobs.get(body.job_id))[0]


@router.put("/answers/{answer_id}")
def edit(answer_id: int, body: AnswerPatch, ctx=Depends(get_ctx)):
    return answers.edit(ctx, answer_id, **body.model_dump())


@router.delete("/answers/{answer_id}")
def delete(answer_id: int, ctx=Depends(get_ctx)):
    ctx.repos.answers.delete(answer_id)
    return {"ok": True}
