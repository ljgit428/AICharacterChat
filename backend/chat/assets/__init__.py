"""Event-sourced character-reference assets.

A user's uploaded reference files (text/image for character setup) are an
append-only ``AssetEvent`` log — the single source of truth. Uploads enter
as ``asset/uploaded`` with a TTL; binding them to a character appends
``asset/attached``; removal appends ``asset/detached``; abandoned staging
files are closed with ``asset/expired``. ``CharacterKnowledgeAsset`` rows are
a materialized projection of that log.
"""
from .store import AssetStore  # noqa: F401
from .projection import AssetFileMissingError, rebuild_character_assets  # noqa: F401
