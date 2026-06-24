# SPDX-License-Identifier: Apache-2.0
"""
tool_registry.py
------------------
In-memory registry of all known tools.
"""

from tools.base import BaseTool
from agent.structs.tool_definition import ToolDefinition

class ToolRegistry:
    """
    Registry of tools 
    Why this exists:
    - To keep track of all available tools.
    - To provide a way to look up tools by name.
    - To provide a way to register new tools.
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(
                f"Tool '{tool.name}' is already registered."
            )
        
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise ValueError(f"Tool '{name}' is not registered.")

        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get_description(self, name: str) -> str:
        return self._tools[name].description
    
    def tool_definitions(self) -> list[ToolDefinition]:
        return [
            tool.definition
            for tool in self._tools.values()
    ]
    # TODO: def unregister(self, name: str) -> None: to remove a tool from the registry. 
    # For now, we can assume that once a tool is registered, it will always be available,
    #  but in the future we may want to add a way to unregister tools that are no longer 
    # needed or have been deprecated.