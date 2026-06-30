# SPDX-License-Identifier: Apache-2.0
"""
debug_client.py
---------------
A "client" that does not call any LLM. Instead, it posts decision
requests to an in-memory queue and blocks until the human operator
submits a decision through the UI.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from client.base_llm_client import BaseLLMClient


@dataclass
class PendingDecision:
    """Represents a decision the human needs to make."""
    id: str
    prompt: str
    response: str | None = None
    event: threading.Event = field(default_factory=threading.Event)


class DebugClient(BaseLLMClient):
    """
    Instead of calling an LLM, this client:
    1. Stores the prompt in a pending queue.
    2. Blocks until a human submits a response via the REST API.
    3. Returns the human response as the "LLM output".
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingDecision] = {}
        self._lock = threading.Lock()

    def generate(self, prompt: str) -> str:
        """Block until a human provides the decision JSON via the UI."""
        decision_id = str(uuid.uuid4())
        pending = PendingDecision(id=decision_id, prompt=prompt)

        with self._lock:
            self._pending[decision_id] = pending

        # Block until the human responds (timeout after 5 minutes)
        pending.event.wait(timeout=300)

        with self._lock:
            self._pending.pop(decision_id, None)

        if pending.response is None:
            return '{"tool": "fail", "reason": "Debug decision timed out", "parameters": {}}'

        return pending.response

    def get_pending(self) -> list[dict[str, Any]]:
        """Return all pending decisions waiting for human input."""
        with self._lock:
            return [
                {"id": p.id, "prompt": p.prompt}
                for p in self._pending.values()
            ]

    def submit_response(self, decision_id: str, response: str) -> bool:
        """Submit a human response for a pending decision."""
        with self._lock:
            pending = self._pending.get(decision_id)

        if pending is None:
            return False

        pending.response = response
        pending.event.set()
        return True
