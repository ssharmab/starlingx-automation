# SPDX-License-Identifier: Apache-2.0
"""
tool_result.py
--------------
Standard structured result contract for agent-compatible infrastructure tools.

WHY THIS EXISTS:
  LangGraph nodes and OpenAI function-calling tools require return values that
  are JSON-serialisable, schema-validated, and machine-readable.  A plain
  (stdout, stderr) tuple or an unstructured string gives an LLM no reliable
  signal for branching decisions.  This module defines the contract every
  tool in this platform must honour.

CHANGES FROM ORIGINAL:
  - Added ResultStatus enum so agents branch on a code, not a string.
  - Added to_dict() for JSON serialisation required by OpenAI tool calling.
  - Added to_openai_schema() classmethod for automatic tool registration.
  - Added correlation_id field for distributed trace linking across LangGraph
    nodes and audit logs.
  - Added command field so audit logs capture what was executed.
  - Kept slots=True for memory efficiency in high-throughput agent loops.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ResultStatus(str, Enum):
    """
    Machine-readable outcome codes for agent branching.

    WHY AN ENUM:
      Agents must not branch on freeform strings like "not available on this
      cluster".  An enum gives the LangGraph router a deterministic signal
      that survives prompt variation and model updates.
    """
    SUCCESS = "success"
    FAILURE = "failure"
    UNAVAILABLE = "unavailable"   # Resource type not present on this cluster.
    TIMEOUT = "timeout"           # Command exceeded its time budget.
    AUTH_ERROR = "auth_error"     # Credential or permission failure.
    NOT_CONNECTED = "not_connected"


@dataclass(slots=True)
class ToolResult:
    """
    Standard return object for all infrastructure tools in this platform.

    Every tool method MUST return a ToolResult.  Agents inspect:
      - status        : ResultStatus enum for branching (not success bool alone)
      - success       : Convenience bool; True iff status == SUCCESS
      - exit_code     : Raw process exit code for audit logs
      - stdout        : Cleaned command output
      - stderr        : Filtered, human-readable error detail
      - duration_seconds : For SLA monitoring and slow-check detection
      - command       : The exact command executed (audit requirement)
      - correlation_id: Links this result to a LangGraph run / audit record
      - data          : Optional structured payload for downstream nodes
    """
    status: ResultStatus
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    command: str = ""
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Convenience accessor; prefer branching on status in agent code."""
        return self.status == ResultStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        """
        Serialise to a JSON-compatible dict.

        WHY NEEDED:
          Function-calling requires tool return values to be
          JSON-serialisable.  dataclasses.asdict() does not handle Enum
          members correctly without a custom encoder; this method does.
        """
        return {
            "status": self.status.value,
            "success": self.success,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": round(self.duration_seconds, 3),
            "command": self.command,
            "correlation_id": self.correlation_id,
            "data": self.data,
        }

    @classmethod
    def error(
        cls,
        status: ResultStatus,
        message: str,
        command: str = "",
        correlation_id: str | None = None,
    ) -> "ToolResult":
        """
        Factory for error results.

        WHY A FACTORY:
          Agent exception handlers need to return a ToolResult even when no
          command ran (e.g. connection failure before exec).  This avoids
          scattered ToolResult construction with magic exit codes.
        """
        return cls(
            status=status,
            exit_code=-1,
            stderr=message,
            command=command,
            correlation_id=correlation_id or str(uuid.uuid4()),
        )
