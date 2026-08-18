"""Salvage → repair → coerce pipeline for model-emitted tool arguments.

Pi's 4-tier defense, ported: (1) JSON salvage that never throws, (2) the spec's
`prepare_arguments` repair hook for known model quirks, (3) a coercing validator that
deletes null optionals / coerces obvious type slips / drops invented fields while SAYING
which ones were dropped, (4) missing-required becomes an actionable error string the loop
returns AS the tool result — the model self-corrects next round instead of the step dying.
"""

from __future__ import annotations

import json
import re

from my_crew.runtime_backends.typed_tool_specs import ToolSpec

_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def salvage_arguments(raw: object) -> dict:
    """Model-emitted arguments string → dict. Degrades to {} — NEVER raises."""
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    for candidate in (
        text,
        _TRAILING_COMMA_RE.sub(r"\1", text),
        _TRAILING_COMMA_RE.sub(r"\1", text).replace("'", '"'),
    ):
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _coerce_value(value: object, expected: str) -> object:
    """Fix the obvious type slips ("7" for an integer, 42 for a string); anything not
    obviously fixable is passed through — the tool's own guard message is more useful
    than a validation failure here."""
    if expected == "integer" and isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return value
    if expected == "number" and isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return value
    if expected == "string" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return value


def coerce_arguments(args: dict, parameters: dict) -> tuple[dict, list[str]]:
    """Schema-aware cleanup: (cleaned_args, names_of_dropped_invented_fields).

    Null optionals are silently deleted (models emit `"days": null` for "not set");
    invented fields are deleted AND reported so the loop can echo them back — silence
    teaches the model the field worked.
    """
    properties: dict = parameters.get("properties") or {}
    required = set(parameters.get("required") or [])
    cleaned: dict = {}
    dropped: list[str] = []
    for key, value in args.items():
        if key not in properties:
            dropped.append(key)
            continue
        if value is None and key not in required:
            continue
        cleaned[key] = _coerce_value(value, str(properties[key].get("type") or ""))
    return cleaned, dropped


def prepare_tool_arguments(
    spec: ToolSpec, raw: object
) -> tuple[dict | None, str | None, list[str]]:
    """Full pipeline for one tool call: (args, error, notes).

    `error` is an instructive string for the model (args is None then); `notes` are
    non-fatal observations (dropped invented fields) to append to the tool result.
    """
    args = salvage_arguments(raw)
    if spec.prepare_arguments is not None:
        try:
            args = spec.prepare_arguments(args)
        except Exception as exc:  # noqa: BLE001 — a repair-hook bug must not kill the loop
            return None, (
                f"Tool {spec.name}: could not prepare arguments ({exc}). "
                f"Call again with arguments matching the schema."
            ), []
    args, dropped = coerce_arguments(args, spec.parameters)
    missing = [k for k in (spec.parameters.get("required") or []) if k not in args]
    if missing:
        return None, (
            f"Tool {spec.name}: missing required parameter(s) {', '.join(missing)}. "
            f"Call again and provide: {', '.join(missing)}."
        ), []
    notes = (
        [f"(ignored unknown parameter(s): {', '.join(sorted(dropped))})"] if dropped else []
    )
    return args, None, notes
