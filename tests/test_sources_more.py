"""New sources (Google Jobs, Adzuna, Reddit, Brave web search) against mocked HTTP."""
import time

import responses

from jobhunter.infrastructure.sources import keyed
from jobhunter.infrastructure.sources.registry import HttpJobSources


@responses.activate
def test_google_jobs_searches_remote_and_home_country():
    responses.get("https://serpapi.com/search.json", json={"jobs_results": [{
        "title": "Backend Engineer", "company_name": "Acme", "location": "Anywhere", "description": "Python APIs",
        "job_id": "abc", "detected_extensions": {"posted_at": "3 days ago", "work_from_home": True},
        "apply_options": [{"title": "LinkedIn", "link": "https://linkedin.com/jobs/1"}]}]})
    jobs = list(keyed.GoogleJobs("key", max_queries=2)(["Backend Engineer"], {"country": "Nigeria"}))
    qs = [c.request.params for c in responses.calls]
    assert qs[0]["q"] == "Backend Engineer remote" and qs[1]["location"] == "Nigeria"
    assert jobs[0]["remote_policy"] == "remote" and jobs[0]["url"] == "https://linkedin.com/jobs/1"
    assert jobs[0]["posted_at"] and jobs[0]["location"] == "Anywhere (Remote)"


@responses.activate
def test_adzuna_parses_and_strips_html():
    responses.get("https://api.adzuna.com/v1/api/jobs/za/search/1", json={"results": [{
        "id": 7, "title": "<strong>Python</strong> Developer", "company": {"display_name": "Cape Co"},
        "location": {"display_name": "Cape Town"}, "description": "Remote-friendly <b>Django</b> role",
        "redirect_url": "https://adzuna/7", "created": "2026-09-20T10:00:00Z", "salary_min": 400000, "salary_max": 600000}]})
    [job] = list(keyed.Adzuna("id", "key", countries=("za",), max_queries=1)(["python developer"]))
    assert job["title"] == "Python Developer" and job["salary"] == "ZAR 400,000–600,000"


@responses.activate
def test_reddit_keeps_hiring_posts_only():
    now = time.time()

    def post(i, title):
        return {"data": {"id": i, "title": title, "selftext": "Node + React, remote", "permalink": f"/r/x/{i}",
                         "created_utc": now - 3600}}
    responses.get("https://www.reddit.com/r/forhire/new.json", json={"data": {"children": [
        post("a", "[Hiring] Full-stack developer, $60/hr"), post("b", "[For Hire] Full-stack dev available"),
        post("c", "Resume review please")]}})
    leads = list(keyed.Reddit(subreddits=("forhire",))([]))
    assert [l["key"] for l in leads] == ["reddit:a"] and leads[0]["lead"]


@responses.activate
def test_web_search_yields_leads_from_web_and_discussions():
    responses.get("https://api.search.brave.com/res/v1/web/search", json={
        "web": {"results": [{"title": "Hiring a backend engineer", "url": "https://acme.io/jobs/1", "description": "Remote"}]},
        "discussions": {"results": [{"title": "Hiring: Node dev", "url": "https://reddit.com/r/x/1", "description": "DM"}]}})
    src = keyed.WebSearch("key", max_queries=1)
    leads = list(src(["Backend Engineer"], {"country": "Nigeria"}))
    assert {l["url"] for l in leads} == {"https://acme.io/jobs/1", "https://reddit.com/r/x/1"}
    assert all(l["fetch"] for l in leads)
    assert "Nigeria" in src.searches(["Backend Engineer"], {"country": "Nigeria"})[0]


def test_unconfigured_keyed_sources_are_skipped_silently():
    src = HttpJobSources(keyed=[keyed.GoogleJobs(""), keyed.WebSearch("")], delay=0)
    assert list(src.collect({}, ["x"], ["google_jobs", "web_search"], keep=lambda j: True)) == []
    status = src.status()["google_jobs"]
    assert status["configured"] is False and status["needs"] == "SERPAPI_API_KEY" and status["keyed"]
