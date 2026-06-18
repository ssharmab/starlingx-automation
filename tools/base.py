from abc import ABC, abstractmethod

from common.tool_result import ToolResult


class BaseTool(ABC):
    """
    Base class for all agent tools.
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    def execute(self, correlation_id: str | None = None) -> ToolResult:
        raise NotImplementedError