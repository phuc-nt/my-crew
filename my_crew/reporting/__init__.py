"""Report artifact builders (xlsx, ...).

Pure, deterministic serializers that turn analyzer dataclasses into file bytes.
No network, no clock, no gateway, no LLM — the caller injects `report_date` and
decides where (or whether) to persist the returned bytes.
"""
