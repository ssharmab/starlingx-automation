# SPDX-License-Identifier: Apache-2.0

from abc import ABC, abstractmethod

from common.tool_request import ToolRequest
from common.tool_result import ToolResult

from agent.structs.tool_definition import ToolDefinition


class BaseTool(ABC):
    """
    Base class for all agent tools.
    """
    
    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """
        Tool metadata exposed to agents.
        """
        pass

    @abstractmethod
    def execute(
        self,
        request: ToolRequest
    ) -> ToolResult:
        pass

    @property
    def name(self) -> str:
        return self.definition.name

    @property
    def description(self) -> str:
        return self.definition.description