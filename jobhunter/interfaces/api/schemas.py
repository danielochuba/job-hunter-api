"""Request bodies (responses are the use cases' dicts)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CVIn(BaseModel):
    name: str
    cv: dict
    is_default: bool = False
    raw_text: str | None = None
    source_file: str | None = None
    contact: dict | None = None


class CVPatch(BaseModel):
    name: str | None = None
    cv: dict | None = None


class CompanyIn(BaseModel):
    url: str | None = None
    source: str | None = None
    token: str | None = None
    name: str | None = None
    domain: str | None = None


class UrlIn(BaseModel):
    url: str


class JobPatch(BaseModel):
    stage: str | None = None
    feedback: Literal["up", "down", "none"] | None = None
    feedback_reason: str | None = None
    notes: str | None = None
    cv_id: int | None = None


class BulkStageIn(BaseModel):
    ids: list[int]
    stage: str


class ImportIn(BaseModel):
    url: str | None = None
    text: str | None = None


class NoteIn(BaseModel):
    note: str


class MatchIn(BaseModel):
    limit: int | None = None
    job_ids: list[int] | None = None


class GenerateIn(BaseModel):
    job_ids: list[int] = []
    top: int | None = None
    cv_id: int | None = None


class JobIdsIn(BaseModel):
    job_ids: list[int]


class JobIdIn(BaseModel):
    job_id: int


class AppEdit(BaseModel):
    result: dict | None = None
    cover_letter: str | None = None


class PreviewIn(BaseModel):
    result: dict


class ContactIn(BaseModel):
    job_id: int
    email: str
    name: str | None = None
    role: str | None = None


class DraftIn(BaseModel):
    job_id: int
    contact_id: int | None = None
    to_email: str | None = None


class OutreachPatch(BaseModel):
    to_email: str | None = None
    subject: str | None = None
    body: str | None = None
    attach_cv: bool | None = None
    status: str | None = None


class ReminderIn(BaseModel):
    job_id: int | None = None
    due_at: datetime
    note: str


class ReminderPatch(BaseModel):
    done: bool | None = None
    due_at: datetime | None = None
    note: str | None = None


class ReadIn(BaseModel):
    ids: list[int] | None = None
