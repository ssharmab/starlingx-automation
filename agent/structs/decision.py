# SPDX-License-Identifier: Apache-2.0
"""
Struct representing a decision made by an agent.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Decision:

    tool: str

    reason: str

    parameters: dict[str, Any] = field(
        default_factory=dict
    )