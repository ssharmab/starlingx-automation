# SPDX-License-Identifier: Apache-2.0
"""
Definition of a tool exposed to an agent.

Why this exists:

- Allows tools to describe themselves.
- Enables LLMs to reason about available tools.
- Provides input/output contracts.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolDefinition:

    name: str

    description: str

    input_schema: dict[str, Any] = field(
        default_factory=dict
    )

    output_schema: dict[str, Any] = field(
        default_factory=dict
    )