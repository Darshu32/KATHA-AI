"""Bundled feed adapters.

Each module exposes one ``build_adapter(settings, *, live: bool)``
factory that returns either the live HTTP adapter or the
deterministic stub used by tests / offline dev.

Adding a new adapter
--------------------
1. Drop a new module here that defines ``LiveAdapter`` + ``StubAdapter``
   subclasses of :class:`app.feeds.base.FeedAdapter` plus a
   ``build_adapter`` factory.
2. Add the import to :func:`app.feeds.registry._bootstrap_default_adapters`.
3. Add a Celery beat schedule entry in
   :mod:`app.workers.celery_app` so refreshes run on cadence.
"""
