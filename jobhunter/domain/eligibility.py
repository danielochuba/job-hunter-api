"""Can the candidate actually take this job? Cheap regex pre-check (saves an LLM call for obvious
no-gos) plus the constraints text given to the scoring model."""
import re

NO_SPONSOR = re.compile(r"(no|not|unable to|cannot|can't|won't|will not|do not|does not)\s+(offer\s+|provide\s+)?"
                        r"(visa\s+)?sponsor", re.I)
CITIZEN_ONLY = re.compile(r"(u\.?s\.?|us|american)\s+citizens?(hip)?\s+(only|required|is required)|"
                          r"must be a (u\.?s\.?|us) citizen|active (security|secret|ts/sci) clearance", re.I)
US_NAMES = {"us", "usa", "united states", "united states of america"}

# "Remote, but only if you live in X" -- the most common reason a remote job is closed to candidates in Africa.
_REGION = (r"(?P<region>u\.?s\.?a?|united states|america|north america|canada|u\.?k\.?|united kingdom|"
           r"e\.?u\.?|european union|europe|eea|australia|germany|india)")
REGION_LOCK = re.compile(
    r"(?:(?:must|need to|required to|should)\s+(?:be\s+)?(?:located|based|residing|reside|live|living)\s+in\s+(?:the\s+)?"
    + _REGION + r"\b"
    r"|\b" + _REGION.replace("?P<region>", "?P<region2>") + r"[\s-]*(?:based\s+)?(?:only|residents only|candidates only|applicants only)\b"
    r"|remote\s*[(\-–,:]\s*" + _REGION.replace("?P<region>", "?P<region3>") + r"\s*(?:only)?\s*\))",
    re.I)
REGION_ALIASES = {
    "us": US_NAMES | {"america", "north america"}, "canada": {"canada", "north america"},
    "uk": {"uk", "united kingdom", "great britain", "england", "europe"},
    "eu": {"eu", "european union", "europe", "eea"}, "australia": {"australia"},
    "germany": {"germany", "eu", "european union"}, "india": {"india"},
}


def _canonical_region(raw):
    r = re.sub(r"[^a-z ]", "", raw.lower()).strip()
    for key, names in REGION_ALIASES.items():
        if r in {re.sub(r"[^a-z ]", "", n) for n in names} or r == key:
            return key
    return r


def region_lock(text, user):
    """Return the region a remote job is restricted to, if the candidate can't work there; else None."""
    m = REGION_LOCK.search(text or "")
    if not m:
        return None
    region = _canonical_region(next(g for g in m.groups() if g))
    # Residency locks are about where you may legally work, so only authorisations and your own
    # country count (acceptable_regions is about timezones you'll work in, e.g. EMEA).
    allowed = {a.lower().strip() for a in (user.get("work_authorizations") or [])}
    allowed |= {(user.get("country") or "").lower().strip()}
    names = REGION_ALIASES.get(region, {region})
    return None if allowed & names else region


def precheck(job, user):
    """Return a reason string if the job is obviously ineligible for the candidate, else None."""
    if not user:
        return None
    text = f"{job.get('title', '')}\n{job.get('location', '')}\n{job.get('description', '')}"
    auths = {a.lower() for a in (user.get("work_authorizations") or [])}
    if CITIZEN_ONLY.search(text) and not (auths & US_NAMES):
        return "Requires US citizenship or security clearance"
    if user.get("needs_sponsorship") and NO_SPONSOR.search(text):
        return "Posting says it does not sponsor visas"
    if user.get("country"):
        region = region_lock(text, user)
        if region:
            return f"Only open to candidates based in {region.upper() if len(region) <= 3 else region.title()}"
    return None


def ineligible_fit(reason, job):
    """A fit result for a pre-checked job, same shape as the LLM's."""
    return {"fit_score": 0, "summary": reason, "eligible": False, "ineligible_reason": reason,
            "matched_requirements": [], "gaps": [], "dealbreakers": [reason], "relevant_bullet_ids": [],
            "remote_policy": job.get("remote_policy") or "unknown", "visa_sponsorship": "unknown",
            "location_restrictions": [], "salary": job.get("salary") or "", "required_skills": [],
            "missing_skills": [], "seniority": "", "prechecked": True}


def constraints_text(user):
    if not user:
        return "none given"
    yes = lambda v: "yes" if v else "no"  # noqa: E731
    parts = [
        f"Based in: {', '.join(x for x in (user.get('city'), user.get('country')) if x) or 'unknown'}",
        f"Needs visa sponsorship: {yes(user.get('needs_sponsorship'))}",
        f"Already authorised to work in: {', '.join(user.get('work_authorizations') or []) or 'home country only'}",
        f"Acceptable regions: {', '.join(user.get('acceptable_regions') or []) or 'any'}",
        f"Remote only: {yes(user.get('remote_only'))}",
        f"Willing to relocate: {yes(user.get('willing_to_relocate'))}",
        f"Target roles: {', '.join(user.get('target_roles') or []) or 'any'}",
        f"Seniority: {user.get('seniority') or 'any'}",
    ]
    if user.get("min_salary"):
        parts.append(f"Minimum salary: {user['min_salary']} {user.get('salary_currency') or ''}".strip())
    return "\n".join(parts)


def feedback_text(examples):
    if not examples:
        return ""
    lines = [f"- {'LIKED' if r['feedback'] == 'up' else 'DISLIKED'}: {r['title']} at {r['company']} "
             f"({r['location']}){' because: ' + r['feedback_reason'] if r.get('feedback_reason') else ''}"
             for r in examples]
    return "PAST FEEDBACK:\n" + "\n".join(lines)


def boosted_similarity(sim, up_sim, dn_sim, weight=0.5):
    """Feedback learning: nudge similarity toward jobs like the ones you liked."""
    sim = float(sim)
    if up_sim is not None and dn_sim is not None:
        sim += weight * (float(up_sim) - float(dn_sim))
    return sim
