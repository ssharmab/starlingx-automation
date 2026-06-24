# SPDX-License-Identifier: Apache-2.0
"""
tool_request.py
--------------
Standard structured request object for agent-compatible tools.

Why this exists:
- Creates a contract for tool inputs.
"""

from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class ToolRequest:
    """Standard request object for infrastructure tools."""

    correlation_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
