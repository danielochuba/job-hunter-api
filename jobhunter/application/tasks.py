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


def daily(run: RunContext, params):
    """Scheduled: collect -> match, due reminders, Gmail reply sync."""
    from .mail import sync_replies
    result = {"collect": collect(run, {})}
    if (run.repos.settings.get()["schedule"] or {}).get("auto_match", True) and run.repos.cvs.any():
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
