"""_template-pack ToolProvider (v20 authoring skeleton).

`TOOL_PROVIDER` is the read seam the report graph asks for source data. A read-only pack can
leave it None (the graph then reads nothing external); a real domain supplies a provider that
conforms structurally to `my_crew.packs.tool_provider.ToolProvider` — see pm-pack/tools.py for the
PM reads and hr-pack/tools.py for a NEW adapter (Google Sheets) the core never knew about.
"""

from __future__ import annotations

#: A real pack sets this to its ToolProvider instance. None ⇒ no external reads.
TOOL_PROVIDER = None
