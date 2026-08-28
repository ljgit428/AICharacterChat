"""Event-sourced chat history.

A chat session's conversation is an append-only ``ChatEvent`` log (the
single source of truth). ``Message`` rows are a materialized projection of
that log, and the model-facing message history is *derived* from it so that
compaction can shadow old events without ever mutating them.
"""
from .store import EventStore  # noqa: F401
from .store import MessageView, estimate_str_tokens, history_tokens  # noqa: F401
