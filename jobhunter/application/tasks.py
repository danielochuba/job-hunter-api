"""Registry of long-running tasks: kind -> fn(run, params). Used by the API (background runs),
the CLI and the scheduler, so all three share one code path."""
from .collect import collect
from .contacts import find as find_contacts
from .generation import generate
from .importing import import_job
from .matching import match
from .notifications import due_reminders
from .prep import prep
from .runs import RunContext


def _auto_match(run: RunContext):
    return (run.repos.settings.get()["schedule"] or {}).get("auto_match", True) and run.repos.cvs.any()


def collect_then_match(run: RunContext, params):
    """What the Collect button does: collect, then (if 'Also match & score' is on) rank the new jobs."""
    result = {"collect": collect(run, params)}
    if _auto_match(run) and result["collect"]["new"]:
        run.log("Matching the new jobs against your CV…")
        result["match"] = match(run, {})
    return result


def daily(run: RunContext, params):
    """Scheduled: collect -> match, due reminders, Gmail reply sync."""
    from .mail import sync_replies
    result = {"collect": collect(run, {})}
    if _auto_match(run):
        result["match"] = match(run, {})
    result["reminders"] = due_reminders(run.app)
    try:
        result["replies"] = sync_replies(run.app, log=run.log)
    except Exception as e:  # noqa: BLE001  gmail problems shouldn't fail the daily run
        run.log(f"! gmail sync: {e}")
    return result


TASKS = {
    "collect": collect,
    "match": match,
    "generate": generate,
    "contacts": find_contacts,
    "prep": prep,
    "import": import_job,
    "daily": daily,
}
