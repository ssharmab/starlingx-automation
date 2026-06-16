# SPDX-License-Identifier: Apache-2.0
"""
tool_registry.py
------------------
In-memory registry of all known tools.
"""

class ToolRegistry:
    """
    Registry of tools 
    Why this exists:
    - To keep track of all available tools.
    - To provide a way to look up tools by name.
    - To provide a way to register new tools.
    """
    