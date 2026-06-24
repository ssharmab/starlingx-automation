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

    data:
        Optional structured payload.

    error_message:
        Human-readable error message if success is False.

    timestamp:
        ISO 8601 timestamp of execution.

    metadata:
        Additional context or information about the execution.

    duration_seconds:
        Time taken to execute the tool.
    """
    success: bool = False
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    data: dict[str, Any] = field(
        default_factory=dict
    )
    error_message: str = ""
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0