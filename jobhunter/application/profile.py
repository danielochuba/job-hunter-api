"""Your user profile and master CVs."""
import uuid

from ..domain.cv import CV_LOCATION_MODES, normalise, summary_stats
from ..domain.errors import InvalidInput, NotFound
from .context import AppContext
from .ingest import parse
from .runs import RunContext

PROFILE_FIELDS = {
    "first_name", "last_name", "preferred_name", "pronouns", "headline", "bio", "email", "phone",
    "phone_country_code", "city", "state_region", "country", "timezone", "linkedin_url", "github_url",
    "portfolio_url", "other_links", "years_experience", "languages", "target_roles", "seniority",
    "employment_types", "needs_sponsorship", "work_authorizations", "acceptable_regions", "remote_only",
    "willing_to_relocate", "min_salary", "salary_currency", "notice_period", "email_signature", "onboarded",
    "cv_location",
}
REQUIRED_FOR_GENERATION = ("first_name", "last_name", "email", "city", "country")
COMPLETENESS = ("first_name", "last_name", "email", "phone", "city", "country", "headline", "linkedin_url",
                "github_url", "target_roles", "seniority", "email_signature")
MAX_UPLOAD = 10 * 1024 * 1024
MAX_AVATAR = 5 * 1024 * 1024


# ---------------------------------------------------------------- profile

def present(ctx: AppContext, user):
    out = dict(user)
    out["avatar_url"] = ctx.storage.signed_url(user["avatar_path"], 3600) if user.get("avatar_path") else None
    out["completeness"] = round(100 * sum(bool(user.get(k)) for k in COMPLETENESS) / len(COMPLETENESS))
    out["missing"] = [k for k in COMPLETENESS if not user.get(k)]
    out["missing_required"] = [k for k in REQUIRED_FOR_GENERATION if not user.get(k)]
    return out


def ensure_user(ctx: AppContext, user_id, email):
    return ctx.repos.users.ensure(user_id, email)


def get_me(ctx: AppContext, user_id):
    user = ctx.repos.users.get(user_id)
    if not user:
        raise NotFound("Profile not found")
    return present(ctx, user)


def update_me(ctx: AppContext, user_id, fields):
    data = {k: v for k, v in fields.items() if k in PROFILE_FIELDS}
    if "cv_location" in data and data["cv_location"] not in CV_LOCATION_MODES:
        raise InvalidInput(f"cv_location must be one of {', '.join(CV_LOCATION_MODES)}")
    if "email" in data and not (data["email"] or "").strip():
        raise InvalidInput("Email can't be empty")
    return present(ctx, ctx.repos.users.update(user_id, **data))


def upload_avatar(ctx: AppContext, user_id, filename, content_type, data):
    if not (content_type or "").startswith("image/"):
        raise InvalidInput("Upload an image")
    if len(data) > MAX_AVATAR:
        raise InvalidInput("Image too large (max 5MB)")
    ext = (filename or "a.png").rsplit(".", 1)[-1].lower()
    path = ctx.storage.upload(f"_avatars/{user_id}-{uuid.uuid4().hex[:8]}.{ext}", data, content_type)
    return present(ctx, ctx.repos.users.update(user_id, avatar_path=path))


# ---------------------------------------------------------------- CVs

def list_cvs(ctx: AppContext):
    return ctx.repos.cvs.list()


def get_cv(ctx: AppContext, cv_id):
    row = ctx.repos.cvs.get(cv_id)
    if not row:
        raise NotFound("CV not found")
    return {**row, "stats": summary_stats(row["cv"]),
            "source_url": ctx.storage.signed_url(row["source_file"], 600) if row.get("source_file") else None}


def create_cv(ctx: AppContext, user_id, name, cv, is_default=False, raw_text=None, source_file=None, contact=None):
    r = ctx.repos
    cv = normalise(cv)
    first = not r.cvs.any()
    row = r.cvs.create(user_id=user_id, name=name.strip() or "Master CV", cv=cv, raw_text=raw_text,
                       source_file=source_file)
    if first or is_default:
        r.cvs.set_default(row["id"])
    if contact:  # from an upload: fill empty profile fields, never overwrite
        current = r.users.get(user_id) or {}
        fill = {k: v for k, v in contact.items()
                if v and k in PROFILE_FIELDS and k != "email" and not current.get(k)}
        if fill:
            r.users.update(user_id, **fill)
    return get_cv(ctx, row["id"])


def update_cv(ctx: AppContext, cv_id, name=None, cv=None):
    get_cv(ctx, cv_id)
    fields = {}
    if name is not None:
        fields["name"] = name
    if cv is not None:
        fields["cv"] = normalise(cv)
    ctx.repos.cvs.update(cv_id, **fields)
    if cv is not None:  # content changed: re-embed on the next match
        ctx.repos.cvs.clear_embedding(cv_id)
    return get_cv(ctx, cv_id)


def delete_cv(ctx: AppContext, cv_id):
    row = get_cv(ctx, cv_id)
    ctx.repos.cvs.delete(cv_id)
    if row["is_default"]:
        remaining = ctx.repos.cvs.list()
        if remaining:
            ctx.repos.cvs.set_default(remaining[0]["id"])


def make_default(ctx: AppContext, cv_id):
    get_cv(ctx, cv_id)
    ctx.repos.cvs.set_default(cv_id)


def duplicate_cv(ctx: AppContext, user_id, cv_id):
    src = get_cv(ctx, cv_id)
    return create_cv(ctx, user_id, f"{src['name']} (copy)", src["cv"], raw_text=src["raw_text"],
                     source_file=src["source_file"])


def store_upload(ctx: AppContext, filename, content_type, data):
    """Validate and keep the original file; returns its storage path."""
    if len(data) > MAX_UPLOAD:
        raise InvalidInput("File too large (max 10MB)")
    if not filename.lower().endswith(ctx.extractor.supported):
        raise InvalidInput("Unsupported file type. Use PDF, DOCX, MD, TXT, JSON or YAML.")
    return ctx.storage.upload(f"_cvs/uploads/{uuid.uuid4().hex[:12]}-{filename}", data,
                              content_type or "application/octet-stream")


def ingest_task(filename, data, source_path):
    """Build the task that parses an uploaded CV; its result is shown to the user for review."""
    def task(run: RunContext, params):
        run.progress(0, 1, "Reading your CV")
        parsed = parse(run, filename, data)
        stats = summary_stats(parsed["cv"])
        run.log(f"Parsed {stats['roles']} roles, {stats['bullets']} bullets from {filename}")
        run.progress(1, 1)
        return {**parsed, "source_file": source_path, "filename": filename}
    return task
