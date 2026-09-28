from dataclasses import dataclass, field

from .ports import (DocumentRenderer, EmailFinder, JobSources, LLMFactory, Mailer, Notifier, Repositories,
                    Scheduler, Storage, TextExtractor, WebPages)


@dataclass
class AppContext:
    """Everything a use case may depend on, injected by the composition root (container.py).
    One context per unit of work (request, run, CLI command): `repos` is bound to one connection."""
    repos: Repositories
    storage: Storage
    sources: JobSources
    web: WebPages
    finder: EmailFinder
    mailer: Mailer
    notifier: Notifier
    renderer: DocumentRenderer
    extractor: TextExtractor
    llm_factory: LLMFactory
    prices: dict = field(default_factory=dict)
    scheduler: Scheduler | None = None
    desktop_notifications: bool = True
