# SPDX-License-Identifier: Apache-2.0
"""
tool_result.py
--------------
Standard structured result object for agent-compatible tools.

Why this exists:
- Agents require structured outputs.
- Exit codes, duration, and error information should be standardized.
- Avoids ad-hoc tuple returns such as (stdout, stderr).
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolResult:
    """
    Standard return object for infrastructure tools.

    success:
        High-level success indicator.

    exit_code:
        Process/command exit code.

    stdout:
        Captured standard output.

    stderr:
        Captured standard error.

    duration_seconds:
        Execution duration.

    data:
        Optional structured payload.
    """
    success: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
