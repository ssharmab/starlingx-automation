# SPDX-License-Identifier: Apache-2.0
"""
Execution history record.

Why this exists:

- Allows reconstruction of agent behavior.
- Captures the observation that led to a decision.
- Captures the result of the executed action.
"""

from dataclasses import dataclass

from common.tool_result import ToolResult
from agent.structs.decision import Decision


@dataclass(slots=True)
class ExecutionRecord:

    observation: ToolResult

    decision: Decision

    result: ToolResult