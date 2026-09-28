"""The truthfulness guard (moved unchanged from Phase 1 generate.py): anything the LLM writes
must trace back to a bullet in the master CV; dates and titles always come from the master."""
from .cv import bullet_index


def validate(result, cv):
    """Drop anything that doesn't trace back to the master CV. Returns (clean, warnings)."""
    idx = bullet_index(cv)
    warnings = []
    for section in ("experience", "projects"):
        valid_parents = {i["id"] for i in cv.get(section, []) or []}
        clean = []
        for item in result[section]:
            if item["id"] not in valid_parents:
                warnings.append(f"dropped unknown {section} id '{item['id']}'")
                continue
            bullets = []
            for b in item["bullets"]:
                src = idx.get(b["source_id"])
                if not src or src[1] != item["id"]:
                    warnings.append(f"dropped bullet with bad source_id '{b['source_id']}'")
                    continue
                bullets.append(b)
            if bullets:
                clean.append({**item, "bullets": bullets})
        result[section] = clean
    all_skills = {s.lower() for group in (cv.get("skills") or {}).values() for s in group}
    kept = [s for s in result["skills_priority"] if s.lower() in all_skills]
    if len(kept) < len(result["skills_priority"]):
        warnings.append("dropped skills not in master CV: "
                        + ", ".join(s for s in result["skills_priority"] if s.lower() not in all_skills))
    result["skills_priority"] = kept
    return result, warnings


def build_cv_context(result, cv):
    """Merge LLM output with master CV metadata (dates/titles always come from the master)."""
    def merge(section):
        by_id = {i["id"]: i for i in cv.get(section, []) or []}
        return [{**by_id[item["id"]], "bullets": [b["text"] for b in item["bullets"]]}
                for item in result[section]]
    return {"cv": cv, "summary": result["summary"], "skills": result["skills_priority"],
            "experience": merge("experience"), "projects": merge("projects")}


def valid_bullet_ids(ids, cv):
    known = bullet_index(cv)
    return [b for b in ids if b in known]
