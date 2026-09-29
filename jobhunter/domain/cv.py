"""Master CV rules. A CV is the Phase 1 YAML shape:

    summary: str
    skills: {group: [skill, ...]}
    experience: [{id, company, title, location, start, end, bullets: [{id, text, skills}]}]
    projects:   [{id, name, url, bullets: [...]}]
    education:  [{institution, degree, start, end}]
    certifications: [str]

Contact details live on the user profile and are overlaid with `with_contact()` wherever the
Phase 1 code expected `cv['name']`, `cv['email']`...
"""
import re

from .errors import InvalidInput


def check_ids(cv):
    """Every role/project/bullet needs an id; bullet ids are unique across the CV."""
    ids = set()
    for section in ("experience", "projects"):
        for item in cv.get(section, []) or []:
            if not item.get("id"):
                raise InvalidInput(f"Every {section} entry needs an id")
            for b in item.get("bullets", []):
                if not b.get("id"):
                    raise InvalidInput(f"Bullet without id in '{item['id']}'")
                if b["id"] in ids:
                    raise InvalidInput(f"Duplicate bullet id: {b['id']}")
                ids.add(b["id"])
    return cv


def dedupe_ids(cv):
    """LLMs occasionally repeat ids; make them unique rather than failing the upload."""
    seen_items, seen_bullets = set(), set()
    for section in ("experience", "projects"):
        for n, item in enumerate(cv.get(section) or [], 1):
            base = re.sub(r"[^a-z0-9-]+", "-", (item.get("id") or f"{section[:3]}-{n}").lower()).strip("-")
            iid, k = base, 2
            while iid in seen_items:
                iid, k = f"{base}-{k}", k + 1
            item["id"] = iid
            seen_items.add(iid)
            for m, b in enumerate(item.get("bullets") or [], 1):
                bid, k = b.get("id") or f"{iid}-{m}", 2
                while bid in seen_bullets:
                    bid, k = f"{iid}-{m}-{k}", k + 1
                b["id"] = bid
                seen_bullets.add(bid)
    return cv


def normalise(cv):
    """Canonical CV dict. Accepts skills as {group: [..]} (Phase 1) or [{group, items}] (LLM schema)."""
    if not isinstance(cv, dict):
        raise InvalidInput("CV must be an object")
    skills = cv.get("skills") or {}
    if isinstance(skills, list):
        skills = {s.get("group") or "Skills": list(s.get("items") or []) for s in skills if s.get("items")}
    elif isinstance(skills, dict):
        skills = {k: list(v or []) for k, v in skills.items()}
    else:
        raise InvalidInput("skills must be an object of groups")
    out = {"summary": (cv.get("summary") or "").strip(), "skills": skills,
           "experience": list(cv.get("experience") or []), "projects": list(cv.get("projects") or []),
           "education": list(cv.get("education") or []), "certifications": list(cv.get("certifications") or [])}
    for section in ("experience", "projects"):
        for item in out[section]:
            item.setdefault("bullets", [])
            for b in item["bullets"]:
                b.setdefault("skills", [])
    return check_ids(dedupe_ids(out))


def contact_from_phase1(cv):
    """Contact block from a Phase 1 master_cv.yaml (name/email/phone/location/links)."""
    first, _, last = (cv.get("name") or "").partition(" ")
    city, _, country = (cv.get("location") or "").partition(",")
    links = {(l.get("label") or "").lower(): l.get("url", "") for l in cv.get("links") or []}
    return {"first_name": first, "last_name": last, "email": cv.get("email", ""), "phone": cv.get("phone", ""),
            "city": city.strip(), "country": country.strip(), "headline": "",
            "linkedin_url": links.get("linkedin", ""), "github_url": links.get("github", ""),
            "portfolio_url": links.get("portfolio", "") or links.get("website", "")}


CV_LOCATION_MODES = ("full", "country", "remote", "hidden")


def utc_offset_label(tz_name):
    """'Africa/Lagos' -> 'UTC+1 (WAT)'. Returns the input unchanged if it isn't an IANA zone."""
    if not tz_name:
        return ""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001  not an IANA name (e.g. "UTC+1"): show as typed
        return tz_name
    mins = int(now.utcoffset().total_seconds() // 60)
    sign, mins = ("+" if mins >= 0 else "-"), abs(mins)
    offset = f"UTC{sign}{mins // 60}" + (f":{mins % 60:02d}" if mins % 60 else "")
    abbr = now.strftime("%Z")
    return f"{offset} ({abbr})" if abbr and not abbr.startswith(("+", "-", "UTC", "GMT")) else offset


def cv_location_text(user):
    """How the location line on a CV reads, per the user's `cv_location` choice."""
    mode = user.get("cv_location") or "full"
    city, country = user.get("city"), user.get("country")
    if mode == "hidden":
        return ""
    if mode == "country":
        return country or ""
    if mode == "remote":
        tz = utc_offset_label(user.get("timezone"))
        return f"Remote · {tz}" if tz else "Remote"
    return ", ".join(x for x in (city, country) if x)


def with_contact(cv, user):
    """Overlay contact details from the user profile onto a CV dict (for templates and prompts)."""
    if not user:
        return cv
    location = cv_location_text(user)
    links = [{"label": label, "url": user[k]} for label, k in
             (("LinkedIn", "linkedin_url"), ("GitHub", "github_url"), ("Portfolio", "portfolio_url"))
             if user.get(k)]
    links += [l for l in (user.get("other_links") or []) if l.get("url")]
    phone = " ".join(x for x in (user.get("phone_country_code"), user.get("phone")) if x)
    return {**cv, "name": user.get("full_name") or cv.get("name", ""),
            "email": user.get("email") or cv.get("email", ""),
            "phone": phone or cv.get("phone", ""),
            # an explicit choice (e.g. hidden) must not fall back to a location stored in the CV itself
            "location": location if user.get("cv_location") not in (None, "full") else (location or cv.get("location", "")),
            "links": links or cv.get("links", []),
            "headline": user.get("headline")}


def as_text(cv):
    """Compact text version of the CV for embeddings and prompts. Bullet ids are kept
    so the model can reference them."""
    lines = [f"Name: {cv.get('name','')}", f"Summary: {(cv.get('summary') or '').strip()}", "Skills:"]
    for group, items in (cv.get("skills") or {}).items():
        lines.append(f"  {group}: {', '.join(items)}")
    lines.append("Experience:")
    for e in cv.get("experience", []) or []:
        lines.append(f"  [{e['id']}] {e.get('title','')} at {e.get('company','')} "
                     f"({e.get('start','')} - {e.get('end','')})")
        for b in e.get("bullets", []):
            lines.append(f"    [{b['id']}] {b['text']}")
    lines.append("Projects:")
    for p in cv.get("projects", []) or []:
        lines.append(f"  [{p['id']}] {p.get('name','')}")
        for b in p.get("bullets", []):
            lines.append(f"    [{b['id']}] {b['text']}")
    lines.append("Education:")
    for ed in cv.get("education", []) or []:
        lines.append(f"  {ed.get('degree','')}, {ed.get('institution','')}")
    return "\n".join(lines)


def bullet_index(cv):
    """Map bullet_id -> (section, parent_id, original_text)."""
    idx = {}
    for section in ("experience", "projects"):
        for item in cv.get(section, []) or []:
            for b in item.get("bullets", []):
                idx[b["id"]] = (section, item["id"], b["text"])
    return idx


def all_skills(cv):
    return [s for group in (cv.get("skills") or {}).values() for s in group]


def summary_stats(cv):
    exp = cv.get("experience") or []
    return {"roles": len(exp), "bullets": sum(len(e.get("bullets") or []) for e in exp),
            "projects": len(cv.get("projects") or []), "skills": len(all_skills(cv))}
