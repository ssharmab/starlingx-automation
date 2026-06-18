from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path

from utils.inventory_checker import InventoryChecker, InventoryConfig, InventoryError
from utils.ssh_connection import SSHConnection, HostKeyPolicy
from utils.tool_result import ToolResult, ResultStatus

logger = logging.getLogger(__name__)

# Kubeconfig path must be a clean absolute POSIX path — no shell metacharacters.
_KUBECONFIG_PATTERN = re.compile(r'^(/[\w.\-]+)+$')

# Default per-command execution timeout in seconds.
DEFAULT_TIMEOUT = 30

# client-go emits these lines on stderr even on successful commands on some
# clusters.  They must be stripped before the success/failure decision.
_MEMCACHE_NOISE = "couldn't get current server API group list"

# These stderr patterns mean the resource type is not registered on this
# cluster — not a command failure, but an UNAVAILABLE signal to the agent.
_UNAVAILABLE_PATTERNS = (
    "the server could not find the requested resource",
    "no matches for kind",
    "the server doesn't have a resource type",
)

# Absolute path to the project root, used by __main__ blocks to locate
# inventory.yaml regardless of the working directory.
_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _build_connection(config: InventoryConfig) -> SSHConnection:
    """
    Construct and connect an SSHConnection from a validated InventoryConfig.

    Centralised here so every __main__ block uses identical connection logic.
    TRUST_ON_FIRST_USE is appropriate for lab/bootstrap use; production
    deployments should pre-populate known_hosts and use STRICT.
    """
    conn = SSHConnection(
        host=config.host,
        login=config.login,
        password=config.password,
        host_key_policy=HostKeyPolicy.TRUST_ON_FIRST_USE,
    )
    conn.connect()
    return conn


def load_inventory(inventory_path: Path | None = None) -> InventoryConfig:
    """
    Load and validate inventory from the default or supplied path.

    Args:
        inventory_path: Override path. Defaults to <project_root>/inventory/inventory.yaml.

    Returns:
        Validated InventoryConfig.

    Raises:
        InventoryError: If validation fails at any stage.
    """
    path = inventory_path or (_PROJECT_ROOT / "inventory" / "inventory.yaml")
    return InventoryChecker(path=path).validate()

