"""Shared constants for the long-term memory subsystem (memory v2 §4).

These are *convention* sections the extraction prompt is trained to use and
the injection layer treats specially. They stay plain strings — the DB schema
has no enum, so user-created sections with other names keep working.
"""

# Single-entry section describing the current relationship stage/atmosphere.
RELATIONSHIP_SECTION = '关系'

# Append-only dated shared experiences ("2026-08-23 第一次一起看了流星雨").
MILESTONE_SECTION = '里程碑'

# Sections that must survive prompt-injection budget trimming in full,
# highest priority first.
PRIORITY_SECTIONS = (RELATIONSHIP_SECTION, MILESTONE_SECTION)

# Injection budget (chars) for the long-term-memory narrative. Trimming is
# per-item inside MemoryManager.get_prompt_memory(); priority sections are
# always preserved in full.
STREAM_MEMORY_SECTION_LIMIT = 6000
