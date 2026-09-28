"""Contact ranking rules (who is worth emailing about a job)."""
import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IGNORE_EMAIL = re.compile(r"(noreply|no-reply|donotreply|example\.|sentry|wixpress|\.png|\.jpg|privacy|legal|abuse)",
                          re.I)
ROLE_WEIGHTS = [(r"recruit|talent|sourc", 30), (r"hiring|people|hr\b|human resources", 20),
                (r"engineering manager|head of engineering|vp.*engineering|director of engineering", 25),
                (r"\bcto\b|chief technology|founder|co-founder|ceo", 15)]
HIRING_LOCALPART = re.compile(r"career|job|recruit|talent|hiring|people", re.I)
GENERIC_INBOXES = ("careers", "jobs")


def extract_emails(text):
    return sorted({e.rstrip(".").lower() for e in EMAIL_RE.findall(text or "") if not IGNORE_EMAIL.search(e)})


def role_bonus(role):
    role = (role or "").lower()
    return max((w for pattern, w in ROLE_WEIGHTS if re.search(pattern, role)), default=0)


def contact(email, source, confidence, name=None, role=None):
    return {"email": email.lower(), "source": source, "confidence": min(100, int(confidence)),
            "name": name, "role": role}


def from_job_post(description):
    return [contact(e, "job_post", 90) for e in extract_emails(description)]


def from_website(email, domain):
    local = email.split("@")[0]
    return contact(email, "website", 45 + (15 if HIRING_LOCALPART.search(local) else 0), role=local)


def from_finder(email, name, role, confidence):
    return contact(email, "hunter", int((confidence or 50) * 0.8) + role_bonus(role), name=name, role=role)


def generic(domain):
    return [contact(f"{p}@{domain}", "pattern", 10, role="generic inbox") for p in GENERIC_INBOXES]


def best_per_email(candidates):
    best = {}
    for c in candidates:
        if c["email"] not in best or c["confidence"] > best[c["email"]]["confidence"]:
            best[c["email"]] = c
    return sorted(best.values(), key=lambda c: -c["confidence"])
