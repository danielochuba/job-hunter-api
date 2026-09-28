"""Job pipeline stages.

new -> filtered_out | ineligible | scored -> generated -> approved | rejected
    -> applied -> interviewing -> offer | closed
"""
STAGES = ("new", "filtered_out", "ineligible", "scored", "generated", "approved", "rejected",
          "applied", "interviewing", "offer", "closed")

# Stages a (re)score may move a job out of; later stages are user decisions and are kept.
RESCORABLE = ("new", "filtered_out", "ineligible", "scored")
# Stages where generating documents advances the job to `generated`.
PRE_GENERATED = ("new", "scored", "filtered_out", "ineligible")
# Stages where sending an outreach email counts as applying.
PRE_APPLIED = ("new", "scored", "generated", "approved")
# Terminal-ish stages that cancel automatic follow-up reminders.
CLOSES_FOLLOWUPS = ("rejected", "closed", "offer")

TRACKER_BOARD = ("generated", "approved", "applied", "interviewing", "offer", "closed")
FUNNEL = ("scored", "generated", "approved", "applied", "interviewing", "offer")


def validate_stage(stage):
    from .errors import InvalidInput
    if stage not in STAGES:
        raise InvalidInput(f"Unknown stage '{stage}'")
    return stage


def label(stage):
    return stage.replace("_", " ").title()


def implicit_feedback(stage):
    """Approving/rejecting a job is feedback for the ranker."""
    return {"approved": "up", "rejected": "down"}.get(stage)


def funnel(counts):
    """Cumulative funnel: a job that reached `offer` also passed every earlier stage."""
    return [{"stage": s, "n": sum(counts.get(t, 0) for t in FUNNEL[i:])} for i, s in enumerate(FUNNEL)]
