"""Composition root: the only place that knows which adapter implements which port."""
from contextlib import contextmanager

from .application.context import AppContext
from .config import Config
from .infrastructure.db.connection import connect, pool
from .infrastructure.db.repositories import PgRepositories
from .infrastructure.documents.renderer import FileTextExtractor, JinjaRenderer
from .infrastructure.hunter import DesktopNotifier, HunterFinder
from .infrastructure.llm.openai_llm import OpenAILLM
from .infrastructure.mail.gmail import GmailMailer
from .infrastructure.sources.registry import HttpJobSources
from .infrastructure.storage.supabase_storage import SupabaseStorage
from .infrastructure.web.pages import HttpWebPages


class Container:
    def __init__(self, config: Config):
        c = self.config = config
        self.storage = SupabaseStorage(c.supabase_url, c.supabase_service_role_key, c.storage_bucket)
        self.sources = HttpJobSources()
        self.web = HttpWebPages()
        self.finder = HunterFinder(c.hunter_api_key)
        self.mailer = GmailMailer(c.google_client_id, c.google_client_secret, c.google_redirect_uri)
        self.notifier = DesktopNotifier()
        self.renderer = JinjaRenderer()
        self.extractor = FileTextExtractor()
        self.scheduler = None  # set by the API when the in-process scheduler starts
        self._pool = None

    def llm_factory(self, on_usage=None):
        c = self.config
        return OpenAILLM(c.openai_api_key or None, c.openai_fast_model, c.openai_strong_model,
                         c.openai_embed_model, on_usage=on_usage)

    def context(self, conn) -> AppContext:
        return AppContext(repos=PgRepositories(conn), storage=self.storage, sources=self.sources, web=self.web,
                          finder=self.finder, mailer=self.mailer, notifier=self.notifier, renderer=self.renderer,
                          extractor=self.extractor, llm_factory=self.llm_factory, prices=self.config.prices,
                          scheduler=self.scheduler, desktop_notifications=self.config.desktop_notifications)

    # ---- units of work
    @contextmanager
    def session(self):
        """A dedicated connection (CLI commands, background runs, scheduled jobs)."""
        with connect(self.config.database_url) as conn:
            yield self.context(conn)

    def open_pool(self):
        self._pool = pool(self.config.database_url)

    def close_pool(self):
        if self._pool:
            self._pool.close()

    @contextmanager
    def pooled(self):
        """A pooled connection (API requests)."""
        with self._pool.connection() as conn:
            yield self.context(conn)
