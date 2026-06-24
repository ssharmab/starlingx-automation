# SPDX-License-Identifier: Apache-2.0
"""
base.py
-------
Abstract base class for all RVMC tools.

LAYER: Tool contract
  Mirrors the pattern established in tools/kubernetes/base.py.
  Every RVMC tool must:
    - declare a name
    - declare a description
    - implement execute() returning a ToolResult

  RvmcBaseTool is never instantiated directly.  VmcObject is the
  only concrete implementation today; future tools (e.g. power-only,
  query-only) inherit from this base without changing the agent contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tools.rvmc.bmc_target import BmcTarget
from common.tool_result import ToolResult
from common.tool_request import ToolRequest
from tools.base import BaseTool


class RvmcBaseTool(BaseTool):
    """
    Abstract base class for all Redfish Virtual Media Controller tools.

    Every subclass MUST declare:
        name        — machine-readable tool identifier
        description — human/agent-readable summary of what the tool does
        execute()   — agent-facing entry point returning a ToolResult

    The constructor accepts a BmcTarget which carries all connection
    parameters.  The tool consumes the target — it does not own
    credentials or manage network topology.
    """

    def __init__(self, target: BmcTarget) -> None:
        """
        Args:
            target: Fully populated BmcTarget. The caller is responsible
                    for sourcing credentials (Secrets Manager, SSM, agent
                    state, etc.).  This class never reads files or env vars.

        Raises:
            TypeError: If target is not a BmcTarget instance.
        """
        if not isinstance(target, BmcTarget):
            raise TypeError(
                f"Expected BmcTarget, got {type(target).__name__}."
            )
        self.target = target

    @abstractmethod
    def execute(self, request: ToolRequest | None = None) -> ToolResult:
        """Execute the tool and return a ToolResult.

        Agents invoke execute() and branch on result.status.
        This method must never call sys.exit() or raise uncaught exceptions —
        all failures must be returned as ToolResult with an appropriate
        ResultStatus.
        """
        pass
