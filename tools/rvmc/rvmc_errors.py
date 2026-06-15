# SPDX-License-Identifier: Apache-2.0
"""
rvmc_errors.py
--------------
Typed exception hierarchy for the Redfish Virtual Media Controller.

Why this exists:
- Replaces all sys.exit() calls so agents can catch, classify, and react to
  failures without the tool terminating the process.
- Each subclass maps to a ResultStatus value in ToolResult so the agent router
  can branch deterministically.
"""
from __future__ import annotations


class RvmcError(Exception):
    """Base exception for all RVMC failures."""
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.message = message
        self.code = code


class RvmcConnectionError(RvmcError):
    """BMC is unreachable or the Redfish client could not be created."""


class RvmcAuthError(RvmcError):
    """Invalid credentials or session creation failure."""


class RvmcPowerError(RvmcError):
    """Host power state transition failed or timed out."""


class RvmcMediaError(RvmcError):
    """Virtual media eject, insert, or verification failure."""


class RvmcBootError(RvmcError):
    """Boot override configuration failed."""


class RvmcConfigError(RvmcError):
    """Config file missing, unreadable, or malformed."""
