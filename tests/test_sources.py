"""Source adapters against mocked HTTP (no network)."""
import responses
from bs4 import BeautifulSoup

from jobhunter.infrastructure.sources import aggregators, ats
from jobhunter.infrastructure.sources.registry import HttpJobSources
from jobhunter.infrastructure.web.pages import jsonld_job


@responses.activate
def test_greenhouse():
    responses.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true", json={"jobs": [
        {"id": 1, "title": "Backend Engineer", "location": {"name": "Remote - EU"}, "absolute_url": "https://x/1",
         "content": "&lt;p&gt;Python &amp; Django&lt;/p&gt;", "updated_at": "2026-09-01T00:00:00Z"}]})
    [job] = list(ats.greenhouse("acme"))
    assert job["key"] == "greenhouse:acme:1"
    assert job["description"] == "Python & Django"
    assert job["remote_policy"] == "remote"


@responses.activate
def test_lever_converts_ms_timestamp_and_workplace():
    responses.get("https://api.lever.co/v0/postings/acme?mode=json", json=[
        {"id": "abc", "text": "API Engineer", "categories": {"location": "London"}, "hostedUrl": "https://l/abc",
         "descriptionPlain": "Build APIs", "lists": [{"text": "You", "content": "<li>Python</li>"}],
         "createdAt": 1767225600000, "workplaceType": "hybrid"}])
    [job] = list(ats.lever("acme"))
    assert job["posted_at"].startswith("2026-01-01")
    assert "Python" in job["description"] and job["remote_policy"] == "hybrid"


@responses.activate
def test_smartrecruiters_fetches_description_only_for_kept_jobs():
    responses.get("https://api.smartrecruiters.com/v1/companies/acme/postings", json={
        "totalFound": 2, "content": [
            {"id": "1", "name": "Backend Engineer", "location": {"city": "Berlin", "remote": True}},
            {"id": "2", "name": "Sales Manager", "location": {"city": "Berlin"}}]})
    responses.get("https://api.smartrecruiters.com/v1/companies/acme/postings/1", json={
        "jobAd": {"sections": {"jobDescription": {"text": "<p>Python</p>"}}}})
    src = HttpJobSources(delay=0)
    out = list(src.collect({"smartrecruiters": ["acme"]}, [], [], keep=lambda j: "Backend" in j["title"]))
    assert [j["title"] for j, _ in out] == ["Backend Engineer"]
    assert "Python" in out[0][0]["description"]
    assert len(responses.calls) == 2  # list + one detail, not two


@responses.activate
def test_collect_isolates_errors_per_source():
    responses.get("https://boards-api.greenhouse.io/v1/boards/broken/jobs?content=true", status=404)
    responses.get("https://remotive.com/api/remote-jobs", json={"jobs": [
        {"id": 9, "title": "Python Dev", "company_name": "R", "url": "u", "description": "d",
         "candidate_required_location": "Worldwide", "publication_date": "2026-09-01"}]})
    src = HttpJobSources(delay=0)
    out = list(src.collect({"greenhouse": ["broken"]}, ["python"], ["remotive"], keep=lambda j: True))
    errors = [e for _, e in out if e]
    jobs = [j for j, _ in out if j]
    assert len(errors) == 1 and "greenhouse/broken" in errors[0]
    assert jobs[0]["location"] == "Remote (Worldwide)"


@responses.activate
def test_remoteok_skips_legal_notice_and_filters_by_query():
    responses.get("https://remoteok.com/api", json=[{"legal": "..."},
        {"id": 1, "position": "Django Developer", "company": "A", "tags": ["python"], "url": "u", "description": "",
         "date": "2026-09-01", "salary_min": 80000, "salary_max": 100000},
        {"id": 2, "position": "Designer", "company": "B", "tags": ["figma"], "url": "u", "description": ""}])
    out = list(aggregators.remoteok(["python"]))
    assert [j["title"] for j in out] == ["Django Developer"]
    assert out[0]["salary"] == "USD 80,000–100,000"


@responses.activate
def test_hn_whoishiring_parses_comment_header():
    responses.get("https://hn.algolia.com/api/v1/search_by_date", json={"hits": [
        {"objectID": "100", "title": "Ask HN: Who is hiring? (September 2026)"}]})
    responses.get("https://hn.algolia.com/api/v1/items/100", json={"children": [
        {"id": 5, "text": "Acme | Senior Backend Engineer | Remote (EU) | Python, Django", "created_at": "2026-09-01"}]})
    [job] = list(aggregators.hn_whoishiring(["python"]))
    assert (job["company"], job["title"], job["location"]) == ("Acme", "Senior Backend Engineer", "Remote (EU)")


def test_jsonld_job_posting():
    html = """<html><script type="application/ld+json">{"@context":"https://schema.org","@graph":[
      {"@type":"JobPosting","title":"Backend Engineer","description":"<p>Build things with Python</p>",
       "datePosted":"2026-09-01","hiringOrganization":{"name":"Acme","sameAs":"https://acme.io"},
       "jobLocationType":"TELECOMMUTE",
       "jobLocation":{"address":{"addressLocality":"Berlin","addressCountry":"DE"}},
       "baseSalary":{"currency":"EUR","value":{"minValue":70000,"maxValue":90000,"unitText":"YEAR"}}}]}
    </script></html>"""
    job = jsonld_job("https://www.linkedin.com/jobs/view/1", BeautifulSoup(html, "html.parser"))
    assert job["company"] == "Acme" and job["company_domain"] == "acme.io"
    assert job["location"] == "Berlin, DE (Remote)" and job["remote_policy"] == "remote"
    assert job["salary"] == "EUR 70000–90000 year"
    assert job["description"] == "Build things with Python"
