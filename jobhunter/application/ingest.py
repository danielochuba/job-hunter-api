"""Turn an uploaded CV (PDF, DOCX, MD, TXT, JSON, YAML) into a master CV + contact details.
The result is returned for review; nothing is saved until the user confirms."""
import json

import yaml

from ..domain.cv import contact_from_phase1, normalise
from ..domain.errors import InvalidInput
from .runs import RunContext

_STR = {"type": "string"}
_BULLETS = {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["id", "text", "skills"],
    "properties": {"id": _STR, "text": _STR, "skills": {"type": "array", "items": _STR}}}}
CONTACT_FIELDS = ("first_name", "last_name", "email", "phone", "city", "country", "headline",
                  "linkedin_url", "github_url", "portfolio_url")

CV_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["contact", "cv"],
    "properties": {
        "contact": {"type": "object", "additionalProperties": False, "required": list(CONTACT_FIELDS),
                    "properties": {k: _STR for k in CONTACT_FIELDS}},
        "cv": {
            "type": "object", "additionalProperties": False,
            "required": ["summary", "skills", "experience", "projects", "education", "certifications"],
            "properties": {
                "summary": _STR,
                "skills": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["group", "items"],
                    "properties": {"group": _STR, "items": {"type": "array", "items": _STR}}}},
                "experience": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["id", "company", "title", "location", "start", "end", "bullets"],
                    "properties": {"id": _STR, "company": _STR, "title": _STR, "location": _STR,
                                   "start": _STR, "end": _STR, "bullets": _BULLETS}}},
                "projects": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["id", "name", "url", "bullets"],
                    "properties": {"id": _STR, "name": _STR, "url": _STR, "bullets": _BULLETS}}},
                "education": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["institution", "degree", "start", "end"],
                    "properties": {"institution": _STR, "degree": _STR, "start": _STR, "end": _STR}}},
                "certifications": {"type": "array", "items": _STR},
            },
        },
    },
}

INGEST_SYSTEM = """You convert a CV into structured JSON for a job-application tool.
Copy facts exactly: do not invent, embellish, merge or summarise achievements. Keep every role,
project and bullet point (split long paragraphs into separate bullets). Use "" for anything missing.
IDs: give every role and project a short kebab-case id (e.g. "acme", "jobhunter"), and every bullet
a unique id prefixed by its parent id (e.g. "acme-1", "acme-2"). Dates as "YYYY-MM" or "YYYY",
and "present" for current roles. Per-bullet `skills` lists technologies mentioned in that bullet.
Group skills sensibly (e.g. Languages, Frameworks, Data, Infra, Tools)."""


def structured_input(filename, text):
    """JSON/YAML that already looks like a master CV skips the LLM."""
    lower = filename.lower()
    try:
        if lower.endswith(".json"):
            data = json.loads(text)
        elif lower.endswith((".yaml", ".yml")):
            data = yaml.safe_load(text)
        else:
            return None
    except (ValueError, yaml.YAMLError) as e:
        raise InvalidInput(f"Could not parse {filename}: {e}") from e
    if isinstance(data, dict) and ("experience" in data or "cv" in data):
        return data
    return None


def parse(run: RunContext, filename, data):
    """Returns {"contact": {...}, "cv": {...}, "raw_text": str}."""
    text = run.app.extractor.extract(filename, data)
    if not text.strip():
        raise InvalidInput("No text found in the file (is it a scanned image PDF?)")
    structured = structured_input(filename, text)
    if structured is not None:
        cv = structured.get("cv", structured)
        contact = structured.get("contact") or contact_from_phase1(cv)
        return {"contact": contact, "cv": normalise(cv), "raw_text": text}
    # Transcription, not judgement: the fast model with low reasoning effort is accurate and far quicker.
    run.log(f"Extracted {len(text):,} characters from {filename}; structuring with {run.llm.fast_model}…")
    res = run.llm.structured(run.llm.fast_model, INGEST_SYSTEM, f"CV ({filename}):\n\n{text[:40000]}",
                             CV_SCHEMA, "master_cv", purpose="ingest", effort="low")
    return {"contact": res["contact"], "cv": normalise(res["cv"]), "raw_text": text}
