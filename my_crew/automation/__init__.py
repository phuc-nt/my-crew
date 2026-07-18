"""D3 workflow automation (v2 M3-P12) — READ-ONLY + PROPOSE.

A declarative `automation.yaml` describes a flat workflow: chain READ steps and PROPOSE
writes by enqueueing them into the EXISTING Lớp B approval queue via the Action Gateway.
The engine NEVER auto-executes a write and imports ONLY the gateway — never a write module.
"""
