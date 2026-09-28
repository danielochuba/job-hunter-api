# job-hunter-api

FastAPI backend and core library for JobHunter, a personal job-search tool. It does the following:

- Collects postings from public ATS APIs, job aggregators and any URL you paste in.
- Ranks them against your CVs.
- Writes a tailored CV and cover letter for each job, with a truthfulness guard.
- Finds contacts, drafts outreach emails and sends them through your Gmail.
- Tracks every application.

The UI lives in [`job-hunter`](https://github.com/danielochuba/job-hunter).

## Architecture

The code follows clean architecture, and dependencies only point inward. `tests/test_architecture.py` enforces this.

```
jobhunter/
  domain/          pure rules, no I/O: truthfulness guard, CV shape, eligibility, stages, pricing, contact ranking
  application/     use cases + ports.py (Protocols for every external dependency)
  infrastructure/  adapters: Postgres repositories, OpenAI, Supabase Storage, Gmail, Hunter,
                   ATS/aggregator sources, web pages (JSON-LD), Jinja/WeasyPrint, PDF/DOCX text extraction
  interfaces/      drivers: FastAPI (api/), CLI (cli.py), in-process scheduler
  container.py     composition root: the only place that wires adapters to ports
  config.py        environment configuration
supabase/migrations/   SQL schema (RLS on every table, no policies)
```

- **Units of work:** a use case receives an `AppContext` holding repositories bound to one connection, plus the adapters it needs.
  - API requests use a pooled connection.
  - Background runs, CLI commands and scheduled jobs each open their own connection.
- **Long tasks:** `collect`, `match`, `generate`, `contacts`, `prep`, `import`, `ingest` and `daily` are registered in `application/tasks.py`.
  - The API, the CLI and the scheduler all run them through `application/runs.py`.
  - Progress, logs and results are written to the `runs` table, and the UI polls it.
- **Data access:** only this API touches the database.
  - Queries go straight to Postgres with psycopg 3.
  - Files go through supabase-py to the private `applications` bucket.
  - The service-role key stays in `.env`.
- **Auth:** every route except `/health` and the Gmail OAuth callback requires a Supabase JWT.
  - It is verified against the project's JWKS, or against the HS256 secret on legacy projects.
  - Only `ALLOWED_USER_EMAIL` is accepted.

## Setup

1. **Python 3.11 or newer.**
   ```bash
   py -3.13 -m venv .venv
   .venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
   pip install -r requirements-dev.txt   # pinned versions (runtime only: requirements.txt)
   pip install -e .                      # makes `python -m jobhunter` / `jobhunter` available
   copy .env.example .env                # then fill it in
   ```
   `pyproject.toml` is the source of truth for dependencies. You can skip the requirements files and use `pip install -e ".[dev]"` to get the latest compatible versions. Add `,pdf` to the extras to get WeasyPrint for PDFs; it needs GTK/Pango, so it's easiest on Linux or Docker.
2. **Supabase.** Create a project, then apply the schema:
   ```bash
   npx supabase login
   npx supabase link --project-ref <ref>
   npx supabase db push
   ```
   Then, in the Supabase dashboard:
   - **Authentication → Users:** add your user, using the same email as `ALLOWED_USER_EMAIL`.
   - **Project Settings → Database:** copy the pooler connection string into `DATABASE_URL`.
3. **Run the API.**
   ```bash
   uvicorn jobhunter.interfaces.api.main:app --reload --port 8000
   ```
   The API docs are at http://localhost:8000/docs.

### Gmail (optional)
1. In Google Cloud Console, create a project and enable the **Gmail API**.
2. Set up the **OAuth consent screen**. Use the External type in Testing mode, and add yourself as a test user.
3. Create **Credentials → OAuth client ID → Web application**, with the redirect URI `http://localhost:8000/gmail/callback`.
4. Put the client ID and secret in `.env`, then click **Connect Gmail** under Settings in the web app.

Emails are only ever sent when you click Send and confirm.

### Hunter.io (optional)
Set `HUNTER_API_KEY` to add Hunter's domain search to contact discovery.

## CLI

The CLI runs the same use cases as the API.

```bash
python -m jobhunter collect | match | daily | list | show ID | generate ID... | generate --top 5
python -m jobhunter import <url> | contacts ID... | prep ID | sync-gmail | approve/reject/applied ID
python -m jobhunter seed-yaml path/to/master_cv.yaml     # bring Phase 1 files across
```

The API has a built-in daily schedule that you set in Settings. If the API isn't running, you can call `python -m jobhunter daily` from cron or Task Scheduler instead.

## Tests

```bash
pytest
```

The tests run offline:
- Domain rules are tested directly.
- Source adapters use mocked HTTP (`responses`).
- Use cases run against in-memory fake repositories and a fake LLM.
- The API is tested for auth and error mapping.
- An architecture test checks the dependency rule.

## Notes
- **LLM spend:** every call is recorded in `llm_usage`. New LLM runs are refused once the month's spend reaches the budget you set in Settings. Prices are defaults in `domain/pricing.py`, so override them with `OPENAI_PRICES` when OpenAI changes them.
- **Sources:** there is no LinkedIn or Indeed crawling, because their terms of service forbid it and they block bots. To add a job from those sites, paste its URL into Import. The importer reads the page's `JobPosting` JSON-LD, or you can paste the description text.
