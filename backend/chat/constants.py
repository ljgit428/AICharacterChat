"""Project-level constants.

The legacy ``world_time``, ``user_persona``, ``enable_web_search``,
``additional_context`` keys were removed from
``DEFAULT_CHAT_SESSION_SETTINGS`` in this PR. Sessions no longer carry
those fields — the values now live as properly-typed columns on
``ChatSession`` / ``UserProfile``. ``output_language`` stays as the
default interface language for callers that want to read it.

The legacy dict itself is preserved as a backwards-compatibility shim
so the historical migration ``0021_userprofile_default_enable_web_search``
keeps importing it on fresh databases. That migration uses the constant
to set a ``BooleanField(default=...)`` value and would otherwise crash
with ``ImportError`` when replayed from scratch. Do NOT use the shim in
new code — the runtime no longer relies on those keys.
"""

from __future__ import annotations

import os

DEFAULT_OUTPUT_LANGUAGE = os.getenv("DEFAULT_CHAT_OUTPUT_LANGUAGE", "Simplified Chinese")


# Backwards-compatibility shim for migration 0021. DO NOT use this dict
# in new runtime code — its keys were migrated to dedicated model
# columns. The values here are the historical defaults that migration
# 0021 originally referenced so fresh database initialization still
# succeeds.
DEFAULT_CHAT_SESSION_SETTINGS = {
    "world_time": "",
    "user_persona": "",
    "enable_web_search": False,
    "additional_context": "",
    "output_language": DEFAULT_OUTPUT_LANGUAGE,
}
