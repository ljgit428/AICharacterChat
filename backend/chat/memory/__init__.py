"""Per-character long-term memory subsystem.

Implements the SonettoHere pattern (file/HTTP exclusions aside): a
Celery-driven per-turn CRUD agent that mutates a DB table mirroring
``memory.yaml``. The DB stays the only source of truth; the
MemoryExplorer VFS renders the table as ``wiki/memory.md``, and the
same snapshot is injected into the system prompt as a
``[LONG-TERM MEMORY]`` block.
"""
from .interface import LongTermMemoryInterface  # noqa: F401
from .manager import MemoryManager  # noqa: F401
