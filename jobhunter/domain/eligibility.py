"""Can the candidate actually take this job? Cheap regex pre-check (saves an LLM call for obvious
no-gos) plus the constraints text given to the scoring model."""
import re

NO_SPONSOR = re.compile(r"(no|not|unable to|cannot|can't|won't|will not|do not|does not)\s+(offer\s+|provide\s+)?"
                        r"(visa\s+)?sponsor", re.I)
CITIZEN_ONLY = re.compile(r"(u\.?s\.?|us|american)\s+citizens?(hip)?\s+(only|required|is required)|"
                          r"must be a (u\.?s\.?|us) citizen|active (security|secret|ts/sci) clearance", re.I)
US_NAMES = {"us", "usa", "united states", "united states of america"}


def precheck(job, user):
    """Return a reason string if the job is obviously ineligible for the candidate, else None."""
    if not user:
        return None
    text = f"{job.get('title', '')}\n{job.get('description', '')}"
    auths = {a.lower() for a in (user.get("work_authorizations") or [])}
    if CITIZEN_ONLY.search(text) and not (auths & US_NAMES):
        return "Requires US citizenship or security clearance"
    if user.get("needs_sponsorship") and NO_SPONSOR.search(text):
        return "Posting says it does not sponsor visas"
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
