import pytest

from jobhunter.domain import contacts, cv as cvmod, eligibility, jobs, pricing, stages
from jobhunter.domain.errors import InvalidInput
from jobhunter.domain.truthfulness import build_cv_context, validate


def result(**over):
    base = {"summary": "s", "skills_priority": ["Python", "Django"], "cover_letter": "x",
            "experience": [{"id": "acme", "bullets": [{"source_id": "acme-2", "text": "Designed DRF APIs"}]}],
            "projects": []}
    return {**base, **over}


# ---------------------------------------------------------------- truthfulness guard

def test_validate_keeps_traceable_content(cv):
    clean, warnings = validate(result(), cv)
    assert warnings == []
    assert clean["experience"][0]["bullets"][0]["source_id"] == "acme-2"


def test_validate_drops_unknown_role_bad_bullets_and_invented_skills(cv):
    r = result(skills_priority=["Python", "Kubernetes"], experience=[
        {"id": "ghost-corp", "bullets": [{"source_id": "acme-1", "text": "x"}]},
        {"id": "acme", "bullets": [{"source_id": "jh-1", "text": "moved from a project"},
                                   {"source_id": "made-up", "text": "invented"},
                                   {"source_id": "acme-1", "text": "ok"}]}])
    clean, warnings = validate(r, cv)
    assert [b["source_id"] for b in clean["experience"][0]["bullets"]] == ["acme-1"]
    assert clean["skills_priority"] == ["Python"]
    assert len(warnings) == 4


def test_build_context_takes_dates_and_titles_from_master(cv):
    ctx = build_cv_context(result(), cv)
    role = ctx["experience"][0]
    assert (role["title"], role["start"], role["bullets"]) == ("Backend Engineer", "2023-06", ["Designed DRF APIs"])


# ---------------------------------------------------------------- CV

def test_normalise_accepts_llm_skill_list_and_dedupes_ids(cv):
    cv["skills"] = [{"group": "Languages", "items": ["Python"]}, {"group": "Empty", "items": []}]
    cv["projects"][0]["bullets"][0]["id"] = "acme-1"  # collides with an experience bullet
    out = cvmod.normalise(cv)
    assert out["skills"] == {"Languages": ["Python"]}
    ids = [b["id"] for s in ("experience", "projects") for i in out[s] for b in i["bullets"]]
    assert len(ids) == len(set(ids))


def test_normalise_rejects_non_object():
    with pytest.raises(InvalidInput):
        cvmod.normalise(["nope"])


def test_with_contact_overlays_profile(cv, user):
    merged = cvmod.with_contact(cv, user)
    assert merged["name"] == "Daniel Example"
    assert merged["location"] == "Lagos, Nigeria"
    assert merged["links"] == [{"label": "LinkedIn", "url": "https://linkedin.com/in/x"}]
    assert "[acme-1]" in cvmod.as_text(merged)


def test_contact_from_phase1():
    c = cvmod.contact_from_phase1({"name": "Ada Lovelace", "location": "London, UK",
                                   "links": [{"label": "GitHub", "url": "https://github.com/ada"}]})
    assert (c["first_name"], c["last_name"], c["country"], c["github_url"]) == \
        ("Ada", "Lovelace", "UK", "https://github.com/ada")


# ---------------------------------------------------------------- eligibility & feedback

@pytest.mark.parametrize("text,reason", [
    ("We are unable to sponsor visas for this role.", "sponsor"),
    ("Must be a US citizen.", "citizenship"),
    ("Active TS/SCI clearance required.", "citizenship"),
    ("We offer visa sponsorship and relocation.", None),
])
def test_precheck(text, reason, user):
    got = eligibility.precheck({"title": "Backend", "description": text}, user)
    assert (got is None) == (reason is None)
    if reason:
        assert reason.split()[0].lower() in got.lower()


def test_precheck_respects_existing_authorisation(user):
    user.update(needs_sponsorship=False, work_authorizations=["United States"])
    assert eligibility.precheck({"title": "", "description": "US citizens only; no sponsorship"}, user) is None


def test_feedback_boost_and_text():
    assert eligibility.boosted_similarity(0.3, 0.8, 0.2, 0.5) == pytest.approx(0.6)
    assert eligibility.boosted_similarity(0.3, 0.8, None) == 0.3
    txt = eligibility.feedback_text([{"feedback": "down", "title": "Sales Eng", "company": "X", "location": "",
                                      "feedback_reason": "not coding"}])
    assert "DISLIKED: Sales Eng at X" in txt and "not coding" in txt


# ---------------------------------------------------------------- jobs, sources, pricing, contacts, stages

def test_fingerprint_ignores_case_and_punctuation():
    assert jobs.fingerprint("Acme, Inc.", "Senior Backend Engineer") == jobs.fingerprint("acme inc", "senior backend engineer!")


def test_passes_filters():
    f = {"title_include": ["backend"], "title_exclude": ["staff"], "locations": ["remote"]}
    assert jobs.passes_filters({"title": "Backend Engineer", "location": "Remote (EU)"}, f)
    assert not jobs.passes_filters({"title": "Staff Backend Engineer", "location": "Remote"}, f)
    assert not jobs.passes_filters({"title": "Backend Engineer", "location": "NYC"}, f)


@pytest.mark.parametrize("url,expected", [
    ("https://boards.greenhouse.io/stripe", ("greenhouse", "stripe")),
    ("https://job-boards.greenhouse.io/airbnb/jobs/123", ("greenhouse", "airbnb")),
    ("https://jobs.lever.co/palantir/abc-123", ("lever", "palantir")),
    ("https://jobs.ashbyhq.com/openai", ("ashby", "openai")),
    ("https://apply.workable.com/acme/j/XYZ/", ("workable", "acme")),
    ("https://jobs.smartrecruiters.com/Bosch/744000", ("smartrecruiters", "Bosch")),
    ("https://acme.recruitee.com/o/dev", ("recruitee", "acme")),
    ("https://example.com/careers", None),
])
def test_match_ats(url, expected):
    assert jobs.match_ats(url) == expected


def test_company_domain_ignores_job_boards():
    assert jobs.company_domain_from_url("https://www.acme.io/careers") == "acme.io"
    assert jobs.company_domain_from_url("https://boards.greenhouse.io/acme") is None


def test_pricing():
    assert pricing.cost("gpt-5-mini-2025-08-07", 1_000_000, 1_000_000) == pytest.approx(2.25)
    assert pricing.cost("unknown-model", 10, 10) == 0.0
    assert pricing.over_budget(20.0, 20) and not pricing.over_budget(5, 0)


def test_contact_ranking():
    cands = (contacts.from_job_post("Apply: jobs@acme.io or no-reply@acme.io")
             + [contacts.from_finder("jane@acme.io", "Jane", "Technical Recruiter", 90)]
             + contacts.generic("acme.io"))
    best = contacts.best_per_email(cands)
    assert [c["email"] for c in best] == ["jane@acme.io", "jobs@acme.io", "careers@acme.io"]
    assert best[0]["confidence"] == 100  # recruiter role bonus, capped
    assert best[1]["source"] == "job_post"  # beats the generic jobs@ guess for the same address


def test_funnel_is_cumulative():
    f = stages.funnel({"scored": 10, "applied": 3, "offer": 1})
    assert [x["n"] for x in f] == [14, 4, 4, 4, 1, 1]


# ---------------------------------------------------------------- query matching & regions

@pytest.mark.parametrize("title,expected", [
    ("Senior Full Stack Engineer", True), ("Fullstack Developer (React/Node)", True), ("NodeJS Developer", True),
    ("Backend Dev - Python", True), ("Product Designer", False), ("Full-Stack Marketing Manager", False),
])
def test_query_match_folds_synonyms(title, expected):
    assert jobs.query_match(title, ["Full-Stack Developer", "Node.js Developer", "Backend Engineer"]) is expected


def test_search_terms_dedupe_and_strip():
    got = jobs.search_terms(["Full-Stack Developer", "Full Stack Developer", "Full-Stack Engineer",
                             "Full-Stack Engineer (AI automation)", "Node.js Developer", "Software Engineer"])
    assert got == ["Full-Stack Developer", "Node.js Developer", "Software Engineer"]


NIGERIA = {"country": "Nigeria", "work_authorizations": ["Nigeria"], "acceptable_regions": ["EMEA", "Worldwide"]}


@pytest.mark.parametrize("location,description,locked", [
    ("Remote (US only)", "", True),
    ("Remote", "Candidates must be located in the United States.", True),
    ("Remote", "EU residents only.", True),
    ("Remote (Worldwide)", "We hire anywhere.", False),
    ("Remote", "Our US team is growing and we hire globally.", False),
])
def test_region_lock_for_candidates_in_africa(location, description, locked):
    reason = eligibility.precheck({"title": "Dev", "location": location, "description": description}, NIGERIA)
    assert (reason is not None) is locked


def test_region_lock_respects_authorisation():
    user = {**NIGERIA, "work_authorizations": ["Nigeria", "United States"]}
    assert eligibility.precheck({"title": "Dev", "location": "Remote (US only)", "description": ""}, user) is None
