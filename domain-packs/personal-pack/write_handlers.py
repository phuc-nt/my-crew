"""personal-pack allowlist (v57) — rỗng có chủ đích.

Thư ký không ghi qua MCP server nào: kênh ra duy nhất là `telegram_send` (native type,
tự có allowlist chat_ids 2 chiều + secret-scan Lớp A riêng, không đi qua allowlist pack).
Allowlist rỗng = default-DENY nguyên vẹn cho mọi mcp_tool.
"""

from __future__ import annotations

#: server → write tool names được phép. Rỗng ⇒ pack không ghi MCP nào.
ALLOWLIST: dict[str, tuple[str, ...]] = {}
