# SPDX-License-Identifier: Apache-2.0
"""
inventory_checker.py
--------------------
Configuration validation layer for the infrastructure AI platform.

LAYER: Configuration / Validation
  This module validates that inventory data is structurally correct and that
  the target host is reachable before any agent workflow begins.  It does NOT
  belong in the transport layer and does NOT perform Kubernetes operations.

CHANGES FROM PREVIOUS VERSION:
  1. SSH connectivity check decoupled from schema validation.
     WHY: The previous implementation opened a full SSH connection just to
     validate credentials.  This doubles SSH round-trips, couples config
     loading to network state, and means validation fails when the network
     is temporarily unreachable even if the inventory is perfectly valid.
     Reachability and SSH auth checks are now separate, optional stages.

  2. validate() returns a typed InventoryConfig dataclass, not a raw dict.
     WHY: Downstream tools and LangGraph nodes that consume inventory data
     need type-safe access.  A raw dict causes KeyError bugs and gives IDEs
     no autocomplete.  A dataclass makes the contract explicit.

  3. kubeconfig path validated with the same regex used in K8sChecker.
     WHY: The kubeconfig path is later interpolated into a shell command.
     Validating it here at load time catches injection attempts before any
     SSH connection is opened.

  4. InventoryError carries a machine_code field for agent branching.
     WHY: Agents must not branch on exception message strings.  A typed
     error code lets LangGraph route to the correct remediation node.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from utils.ssh_connection import SSHConnection, HostKeyPolicy

logger = logging.getLogger(__name__)

_REQUIRED_KEYS = ("host", "login", "password", "namespace", "kubeconfig")

# Same pattern used in K8sChecker — validated once here at load time.
_KUBECONFIG_PATTERN = re.compile(r'^(/[\w.\-]+)+$')

_DEFAULT_INVENTORY_PATH = Path(__file__).parent.parent / "inventory" / "inventory.yaml"


class InventoryErrorCode(str, Enum):
    """
    Machine-readable error codes for agent branching.

    WHY AN ENUM:
      LangGraph conditional edges must not branch on exception message strings.
      A typed code lets the router direct control to the correct remediation
      node (e.g. SECRET_REFRESH, HOST_UNREACHABLE handler, CONFIG_ERROR).
    """
    FILE_NOT_FOUND = "file_not_found"
    INVALID_YAML = "invalid_yaml"
    MISSING_KEYS = "missing_keys"
    EMPTY_VALUES = "empty_values"
    INVALID_HOST = "invalid_host"
    INVALID_KUBECONFIG = "invalid_kubeconfig"
    HOST_UNREACHABLE = "host_unreachable"
    SSH_AUTH_FAILED = "ssh_auth_failed"
    SSH_CONNECT_FAILED = "ssh_connect_failed"


class InventoryError(Exception):
    """
    Raised when inventory validation fails.

    Carries a machine_code so LangGraph conditional edges can route to
    the correct remediation node without parsing the message string.
    """
    def __init__(self, message: str, code: InventoryErrorCode) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class InventoryConfig:
    """
    Typed, immutable inventory configuration.

    WHY FROZEN DATACLASS:
      Inventory config is read-once at workflow start and must not be
      mutated by downstream nodes.  frozen=True enforces this contract.
      Type hints give IDEs and static analysers full visibility.
    """
    host: str
    login: str
    password: str
    namespace: str
    kubeconfig: str


class InventoryChecker:
    """
    Validates inventory.yaml and returns a typed InventoryConfig.

    Validation stages (each raises InventoryError with a specific code):
      1. File exists and is valid YAML.
      2. All required keys are present and non-empty.
      3. Host is a valid IP address.
      4. kubeconfig path passes the safety pattern.
      5. (Optional) Host is TCP-reachable on port 22.
      6. (Optional) SSH credentials are accepted.

    Stages 5 and 6 are optional and controlled by check_reachability and
    check_ssh_access constructor arguments.  This allows validation to
    succeed in CI/CD pipelines that cannot reach the target host.

    Attributes:
        path (Path):              Resolved path to the inventory file.
        timeout (int):            TCP/SSH connection timeout in seconds.
        check_reachability (bool): Whether to probe port 22.
        check_ssh_access (bool):  Whether to perform an SSH auth handshake.
    """

    def __init__(
        self,
        path: str | Path = _DEFAULT_INVENTORY_PATH,
        timeout: int = 10,
        check_reachability: bool = True,
        check_ssh_access: bool = True,
    ) -> None:
        self.path = Path(path).resolve()
        self.timeout = timeout
        self.check_reachability = check_reachability
        self.check_ssh_access = check_ssh_access
        logger.debug("InventoryChecker initialised for '%s'.", self.path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if not self.path.is_file():
            raise InventoryError(
                f"Inventory file not found: '{self.path}'.",
                InventoryErrorCode.FILE_NOT_FOUND,
            )
        with self.path.open() as fh:
            try:
                data = yaml.safe_load(fh)
            except yaml.YAMLError as exc:
                raise InventoryError(
                    f"Invalid YAML in '{self.path}': {exc}",
                    InventoryErrorCode.INVALID_YAML,
                ) from exc
        if not isinstance(data, dict):
            raise InventoryError(
                f"Inventory must be a YAML mapping, got {type(data).__name__}.",
                InventoryErrorCode.INVALID_YAML,
            )
        return data

    def _validate_schema(self, data: dict) -> None:
        missing = [k for k in _REQUIRED_KEYS if k not in data]
        if missing:
            raise InventoryError(
                f"Missing required keys: {missing}.",
                InventoryErrorCode.MISSING_KEYS,
            )
        empty = [k for k in _REQUIRED_KEYS if not str(data[k]).strip()]
        if empty:
            raise InventoryError(
                f"Empty values for keys: {empty}.",
                InventoryErrorCode.EMPTY_VALUES,
            )

    def _validate_host(self, host: str) -> None:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            raise InventoryError(
                f"'{host}' is not a valid IPv4 or IPv6 address.",
                InventoryErrorCode.INVALID_HOST,
            )

    def _validate_kubeconfig(self, kubeconfig: str) -> None:
        if not _KUBECONFIG_PATTERN.match(kubeconfig):
            raise InventoryError(
                f"kubeconfig path '{kubeconfig}' contains invalid characters.",
                InventoryErrorCode.INVALID_KUBECONFIG,
            )

    def _check_reachability(self, host: str) -> None:
        logger.info("Checking TCP reachability of '%s':22 ...", host)
        try:
            family = (
                socket.AF_INET6
                if isinstance(ipaddress.ip_address(host), ipaddress.IPv6Address)
                else socket.AF_INET
            )
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((host, 22))
            sock.close()
            logger.info("Host '%s' is reachable on port 22.", host)
        except socket.timeout:
            raise InventoryError(
                f"Host '{host}' unreachable: port 22 timed out after {self.timeout}s.",
                InventoryErrorCode.HOST_UNREACHABLE,
            )
        except OSError as exc:
            raise InventoryError(
                f"Host '{host}' unreachable: {exc}.",
                InventoryErrorCode.HOST_UNREACHABLE,
            )

    def _check_ssh_access(self, host: str, login: str, password: str) -> None:
        """
        Verify SSH credentials with a minimal connect/disconnect.

        WHY SEPARATE FROM REACHABILITY:
          TCP reachability (port 22 open) does not prove credentials work.
          A host can be reachable but locked out.  Separating the checks
          gives the agent precise error codes for targeted remediation.
        """
        logger.info("Verifying SSH access to '%s' as '%s' ...", host, login)
        try:
            conn = SSHConnection(
                host=host, login=login, password=password,
                host_key_policy=HostKeyPolicy.TRUST_ON_FIRST_USE,
                connect_timeout=self.timeout,
            )
            conn.connect()
            conn.disconnect()
            logger.info("SSH access to '%s' confirmed.", host)
        except ConnectionAbortedError as exc:
            raise InventoryError(str(exc), InventoryErrorCode.SSH_CONNECT_FAILED)
        except (socket.timeout, OSError) as exc:
            raise InventoryError(
                f"SSH connection to '{host}' failed: {exc}",
                InventoryErrorCode.SSH_CONNECT_FAILED,
            )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def validate(self) -> InventoryConfig:
        """
        Run all validation stages and return a typed InventoryConfig.

        Returns:
            InventoryConfig — typed, immutable, ready for downstream tools.

        Raises:
            InventoryError — with a machine_code for agent branching.
        """
        logger.info("Validating inventory: '%s'.", self.path)
        data = self._load()
        self._validate_schema(data)
        self._validate_host(data["host"])
        self._validate_kubeconfig(data["kubeconfig"])

        if self.check_reachability:
            self._check_reachability(data["host"])
        if self.check_ssh_access:
            self._check_ssh_access(data["host"], data["login"], data["password"])

        config = InventoryConfig(
            host=data["host"],
            login=data["login"],
            password=data["password"],
            namespace=data["namespace"],
            kubeconfig=data["kubeconfig"],
        )
        logger.info("Inventory validation passed for host '%s'.", config.host)
        return config


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Validate the default inventory and print a summary."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )
    try:
        config = InventoryChecker().validate()
        print("\nInventory validation successful.")
        print(f"  Host       : {config.host}")
        print(f"  Login      : {config.login}")
        print(f"  Namespace  : {config.namespace}")
        print(f"  Kubeconfig : {config.kubeconfig}")
    except InventoryError as exc:
        logger.error("Inventory validation failed [%s]: %s", exc.code.value, exc)


if __name__ == "__main__":
    main()
