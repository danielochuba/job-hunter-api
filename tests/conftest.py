import copy

import pytest

MASTER_CV = {
    "summary": "Backend engineer with 2+ years building Python/Django and Node services.",
    "skills": {"Languages": ["Python", "TypeScript", "SQL"], "Frameworks": ["Django", "FastAPI"],
               "Data": ["PostgreSQL", "Redis"]},
    "experience": [{
        "id": "acme", "company": "Acme Ltd", "title": "Backend Engineer", "location": "London",
        "start": "2023-06", "end": "present",
        "bullets": [
            {"id": "acme-1", "text": "Built a reusable ticketing package used by 6 internal products.", "skills": []},
            {"id": "acme-2", "text": "Designed REST APIs in Django REST Framework serving 40k daily requests.",
             "skills": []},
        ]}],
    "projects": [{"id": "jobhunter", "name": "JobHunter", "url": "",
                  "bullets": [{"id": "jh-1", "text": "Built an LLM job-ranking pipeline.", "skills": []}]}],
    "education": [{"institution": "Uni", "degree": "BSc CS", "start": "2019", "end": "2022"}],
    "certifications": [],
}

USER = {"id": "u1", "email": "me@example.com", "first_name": "Daniel", "last_name": "Example",
        "full_name": "Daniel Example", "city": "Lagos", "country": "Nigeria", "needs_sponsorship": True,
        "work_authorizations": ["Nigeria"], "acceptable_regions": ["EMEA"], "target_roles": ["Backend Engineer"],
        "linkedin_url": "https://linkedin.com/in/x", "github_url": "", "portfolio_url": "", "other_links": []}


@pytest.fixture
def cv():
    return copy.deepcopy(MASTER_CV)


@pytest.fixture
def user():
    return dict(USER)
