"""Shared surface for the per-agent Agent Studio routes (v7 M18). Telegram bind (M18a) and
the knowledge/skills form (M18b) live in separate route modules but mount on ONE router with a
common `/api/agents` prefix and share the same agent-id guard, so they behave as one API."""

from __future__ import annotations

import re

from fastapi import APIRouter

# One router shared by both studio route modules — each imports it and hangs its endpoints off
# it, so app.py includes a single router (order-independent, same prefix/tags).
router = APIRouter(prefix="/api/agents", tags=["agent-studio"])

_AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
