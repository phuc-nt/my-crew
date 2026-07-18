"""FastAPI web service for the multi-agent platform (v2 M2-P6).

Localhost-only, no-auth dashboard backend: lists agents, surfaces per-agent status
(budget / pending approvals / last run), triggers on-demand report runs in-process,
and streams their live node-progress over SSE. Scheduled runs stay on the worker
subprocess path (P3 service) — this is the on-demand + observability surface.
"""
