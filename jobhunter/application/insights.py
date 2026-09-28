"""Skill-gap report: what good-fit jobs keep asking for that the CV doesn't show."""
from ..domain.cv import all_skills
from .context import AppContext


def skill_gaps(ctx: AppContext, min_fit=60, limit=25):
    jobs = ctx.repos.jobs
    missing = jobs.skill_counts("missing_skills", min_fit, limit)
    demanded = jobs.skill_counts("required_skills", min_fit, 60)
    cv = ctx.repos.cvs.default()
    have = {s.lower() for s in all_skills(cv["cv"])} if cv else set()
    return {
        "min_fit": min_fit,
        "jobs_considered": jobs.count_fit_at_least(min_fit),
        "missing": [{k: m[k] for k in ("skill", "jobs", "avg_fit", "examples")} for m in missing],
        "strengths": [{"skill": d["skill"], "jobs": d["jobs"]} for d in demanded if d["skill"].lower() in have][:15],
    }
