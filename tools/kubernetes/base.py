# SPDX-License-Identifier: Apache-2.0
"""
base.py
-------
Abstract base class for all Kubernetes SSH tools.

LAYER: Tool
  Centralises the env_prefix construction, memcache noise filtering, and
  the _run() execution contract so each individual tool file contains only
  its own command logic and test harness.

  Individual tools (get_nodes, get_pods, etc.) inherit from KubernetesTool,
  declare name/description, and implement execute().  They call
  self._run("kubectl ...") exclusively.  They never access conn._client
  directly and never construct commands from external input.
"""

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


class KubernetesTool(ABC):
    """
    Abstract base class for all Kubernetes SSH tools.

    Every subclass MUST declare:
        name        — machine-readable tool identifier
        description — human/agent-readable summary of what the tool does
        execute()   — the agent-facing entry point returning a ToolResult

    Subclasses call self._run("kubectl <subcommand>") internally.
    No subclass may access self.conn._client directly, construct commands
    from external input, or call print().
    """

    name: str = ""
    description: str = ""

    def __init__(
        self,
        conn: SSHConnection,
        namespace: str = "default",
        kubeconfig: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """
        Args:
            conn:       An already-connected SSHConnection instance.
                        The tool consumes the transport — it does not own
                        credentials or manage connection lifecycle.
            namespace:  Default Kubernetes namespace for namespaced queries.
            kubeconfig: Absolute path to kubeconfig on the remote host.
                        Validated against ^(/[\\w.\\-]+)+$ to prevent injection.
            timeout:    Per-command SSH execution timeout in seconds.

        Raises:
            TypeError:  If conn is not an SSHConnection.
            ValueError: If kubeconfig fails the safety pattern.
        """
        if not isinstance(conn, SSHConnection):
            raise TypeError(f"Expected SSHConnection, got {type(conn).__name__}.")
        if kubeconfig and not _KUBECONFIG_PATTERN.match(kubeconfig):
            raise ValueError(
                f"kubeconfig path '{kubeconfig}' contains invalid characters."
            )
        self.conn = conn
        self.namespace = namespace
        self.timeout = timeout
        self._env_prefix = f"export KUBECONFIG={kubeconfig} && " if kubeconfig else ""

    @classmethod
    def from_inventory(cls, config: InventoryConfig, conn: SSHConnection) -> "KubernetesTool":
        """
        Construct this tool from a validated InventoryConfig.

        Ensures namespace and kubeconfig always come from the validated
        inventory source, not from ad-hoc constructor arguments.
        """
        return cls(
            conn=conn,
            namespace=config.namespace,
            kubeconfig=config.kubeconfig,
        )

    @abstractmethod
    def execute(self, correlation_id: str | None = None) -> ToolResult:
        """
        Execute the tool and return a ToolResult.

        Every subclass must implement this as the agent-facing entry point.
        Agents invoke execute() and branch on result.status — they never
        call individual query methods directly.
        """

    def _ns_flag(self, namespace: str | None) -> str:
        """Return the kubectl namespace flag string."""
        ns = namespace or self.namespace
        return "--all-namespaces" if ns == "--all-namespaces" else f"-n {ns}"

    def _run(self, command: str, correlation_id: str | None = None) -> ToolResult:
        """
        Execute a pre-approved kubectl command via conn.execute().

        Strips memcache noise from stderr before making the success/failure
        decision.  Maps resource unavailability patterns to UNAVAILABLE status
        so agents branch to a skip path, not a remediation path.

        Args:
            command:        A fixed kubectl command string. Never constructed
                            from user or LLM input.
            correlation_id: Trace ID propagated through audit logs.

        Returns:
            ToolResult — always. Never raises.
        """
        prefixed = self._env_prefix + command
        result = self.conn.execute(prefixed, timeout=self.timeout,
                                   correlation_id=correlation_id)

        # Strip client-go memcache noise line by line.
        clean_stderr = "\n".join(
            line for line in result.stderr.splitlines()
            if _MEMCACHE_NOISE not in line
        ).strip()

        # Memcache noise was the only stderr content and stdout has output
        # → the command actually succeeded despite exit code 1.
        if not result.success and not clean_stderr and result.stdout.strip():
            return ToolResult(
                status=ResultStatus.SUCCESS,
                exit_code=0,
                stdout=result.stdout.strip(),
                stderr="",
                duration_seconds=result.duration_seconds,
                command=command,
                correlation_id=result.correlation_id,
            )

        # Resource type not available on this cluster → UNAVAILABLE, not FAILURE.
        if not result.success and any(p in clean_stderr for p in _UNAVAILABLE_PATTERNS):
            logger.warning("Resource not available on this cluster: %s", command)
            return ToolResult(
                status=ResultStatus.UNAVAILABLE,
                exit_code=result.exit_code,
                stdout="",
                stderr="not available on this cluster",
                duration_seconds=result.duration_seconds,
                command=command,
                correlation_id=result.correlation_id,
            )

        return ToolResult(
            status=result.status,
            exit_code=result.exit_code,
            stdout=result.stdout.strip(),
            stderr=clean_stderr,
            duration_seconds=result.duration_seconds,
            command=command,
            correlation_id=result.correlation_id,
        )
