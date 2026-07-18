"""SMTP delivery config (M3-P11 D2) — outbound email channel.

Kept separate from `reporting_config.py` to stay under the LOC gate. The password is
NOT a field here: it is read from `os.environ["SMTP_PASSWORD"]` inside the send handler
at send time, so a credential never lives in a committed profile, the audit log, or the
approval store. This mirrors how the MCP server specs keep tokens out of the action dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SmtpConfig:
    """How to reach the SMTP server + the default report recipients.

    `use_tls=True` ⇒ STARTTLS on the given port (587 default). Port-465 implicit SSL is a
    deferred toggle. The password is resolved from env at send time, never stored here.
    """

    smtp_host: str
    smtp_user: str
    from_addr: str
    smtp_port: int = 587
    use_tls: bool = True
    recipients: tuple[str, ...] = field(default_factory=tuple)
