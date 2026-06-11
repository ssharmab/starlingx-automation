# SPDX-License-Identifier: Apache-2.0
"""
ssh_connection.py
-----------------
Production-grade SSH transport layer for the infrastructure AI platform.

LAYER: Transport
  This module ONLY handles SSH connectivity and command execution.
  It has no knowledge of Kubernetes, StarlingX, inventories, or agent logic.
  Higher layers (tool, workflow, agent) depend on this; it depends on nothing
  above it.

CHANGES FROM PREVIOUS VERSION:
  1. Thread safety: added threading.Lock around _client access.
     WHY: LangGraph parallel nodes share tool instances; without a lock,
     concurrent exec_command calls corrupt the Paramiko channel state.

  2. Retry logic with exponential backoff on execute().
     WHY: Transient SSH channel errors must not abort an entire agent workflow.
     Infrastructure networks are noisy; one retry saves a full re-plan cycle.

  3. Structured audit logging via _audit_log().
     WHY: Every command executed on a production cluster must be recorded
     immutably with host, user, command, exit code, duration, and
     correlation ID for SOC2 / compliance audit trails.

  4. ResultStatus integration in execute().
     WHY: Agents must branch on a typed enum, not parse booleans or strings.

  5. is_connected property.
     WHY: LangGraph nodes that receive a pre-built connection object need to
     verify liveness before use, without triggering a full reconnect.

  6. execute() now captures command in ToolResult.
     WHY: Audit requirement — the result must carry what was run.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import threading
import time
from enum import Enum

import paramiko

from utils.tool_result import ToolResult, ResultStatus

logger = logging.getLogger(__name__)

# Audit logger writes to a separate handler so audit records can be
# routed to an immutable sink (S3, CloudWatch Logs, SIEM) independently
# of the application log stream.
audit_logger = logging.getLogger("audit.ssh")


class HostKeyPolicy(str, Enum):
    """
    Agent-compatible host key policies.

    STRICT:
        Host must already be in known_hosts.  Use in production after
        bootstrap.  Prevents MITM silently accepting rogue keys.

    TRUST_ON_FIRST_USE:
        Unknown keys are persisted automatically.  Use during initial
        cluster bootstrap only.  Must not be the default in production.
    """
    STRICT = "STRICT"
    TRUST_ON_FIRST_USE = "TRUST_ON_FIRST_USE"


def _load_inventory(path: str) -> dict:
    """Load and minimally validate an inventory YAML file."""
    import yaml
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Inventory file not found: '{path}'.")
    with open(path) as fh:
        data = yaml.safe_load(fh)
    missing = [k for k in ("host", "login", "password") if k not in data]
    if missing:
        raise ValueError(f"Inventory is missing keys: {missing}.")
    return data


class SSHConnection:
    """
    Thread-safe SSH transport with structured result contract.

    LAYER: Transport
      Exposes connect(), execute(), disconnect() and nothing else to callers.
      All Paramiko internals are private.  Higher layers MUST NOT access
      _client directly — doing so bypasses the lock, the audit log, and the
      retry logic.
    """

    def __init__(
        self,
        host: str,
        login: str,
        password: str,
        port: int = 22,
        host_key_policy: HostKeyPolicy = HostKeyPolicy.STRICT,
        connect_timeout: int = 10,
        max_retries: int = 2,
    ) -> None:
        """
        Args:
            host:             IPv4 or IPv6 address of the remote host.
            login:            SSH username.
            password:         SSH password.
            port:             SSH port (default 22).
            host_key_policy:  STRICT or TRUST_ON_FIRST_USE.
            connect_timeout:  TCP/SSH handshake timeout in seconds.
            max_retries:      Number of execute() retries on transient errors.
                              Does NOT retry authentication failures.
        """
        self.host = host
        self.login = login
        self.password = password
        self.port = port
        self.host_key_policy = host_key_policy
        self.connect_timeout = connect_timeout
        self.max_retries = max_retries

        self._client: paramiko.SSHClient | None = None
        # WHY A LOCK: LangGraph parallel branches may call execute() on the
        # same SSHConnection concurrently.  Paramiko's SSHClient is not
        # thread-safe; the lock serialises channel creation.
        self._lock = threading.Lock()
        self.ip_version = self._detect_ip_version(host)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_ip_version(self, host: str) -> int:
        return ipaddress.ip_address(host).version

    def _get_socket_family(self) -> socket.AddressFamily:
        return socket.AF_INET if self.ip_version == 4 else socket.AF_INET6

    @staticmethod
    def _known_hosts_path() -> str:
        return os.path.join(os.path.expanduser("~"), ".ssh", "known_hosts")

    def _fetch_remote_host_key(self, sock: socket.socket) -> paramiko.PKey:
        transport = paramiko.Transport(sock)
        try:
            transport.start_client()
            return transport.get_remote_server_key()
        finally:
            transport.close()

    def _persist_host_key(self, host_key: paramiko.PKey) -> None:
        known_hosts = self._known_hosts_path()
        os.makedirs(os.path.dirname(known_hosts), mode=0o700, exist_ok=True)
        host_keys = paramiko.HostKeys()
        if os.path.isfile(known_hosts):
            host_keys.load(known_hosts)
        host_keys.add(self.host, host_key.get_name(), host_key)
        host_keys.save(known_hosts)

    def _audit_log(
        self,
        command: str,
        result: ToolResult,
    ) -> None:
        """
        Write a structured audit record for every executed command.

        WHY THIS EXISTS:
          Production infrastructure operators require an immutable record of
          every command run on every host, including who ran it, when, the
          exact command string, the exit code, and the duration.  This is a
          SOC2 / CIS Controls requirement.  The audit logger is a separate
          named logger so ops teams can route it to CloudWatch Logs, S3, or a
          SIEM without modifying application log routing.
        """
        audit_logger.info(
            '{"event":"ssh_exec","host":"%s","user":"%s","command":"%s",'
            '"exit_code":%d,"status":"%s","duration_seconds":%.3f,'
            '"correlation_id":"%s"}',
            self.host,
            self.login,
            command.replace('"', '\\"'),
            result.exit_code,
            result.status.value,
            result.duration_seconds,
            result.correlation_id,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """
        True if the underlying transport is active.

        WHY NEEDED:
          LangGraph nodes that receive a pre-built SSHConnection via state
          must verify liveness before issuing commands, without triggering
          a full reconnect.
        """
        with self._lock:
            if self._client is None:
                return False
            transport = self._client.get_transport()
            return transport is not None and transport.is_active()

    def connect(self) -> None:
        """Open the SSH connection. Idempotent if already connected."""
        if self.is_connected:
            return

        logger.info("Connecting to %s (IPv%d) as '%s'.", self.host, self.ip_version, self.login)

        sock = socket.socket(self._get_socket_family(), socket.SOCK_STREAM)
        sock.settimeout(self.connect_timeout)
        sock.connect((self.host, self.port))

        known_hosts = self._known_hosts_path()
        host_keys = paramiko.HostKeys()
        if os.path.isfile(known_hosts):
            host_keys.load(known_hosts)

        if host_keys.lookup(self.host) is None:
            if self.host_key_policy == HostKeyPolicy.STRICT:
                raise ConnectionAbortedError(f"{self.host} not in known_hosts.")
            remote_key = self._fetch_remote_host_key(sock)
            self._persist_host_key(remote_key)
            sock = socket.socket(self._get_socket_family(), socket.SOCK_STREAM)
            sock.settimeout(self.connect_timeout)
            sock.connect((self.host, self.port))

        with self._lock:
            self._client = paramiko.SSHClient()
            self._client.set_missing_host_key_policy(paramiko.RejectPolicy())
            if os.path.isfile(known_hosts):
                self._client.load_host_keys(known_hosts)
            self._client.connect(
                hostname=self.host,
                port=self.port,
                username=self.login,
                password=self.password,
                sock=sock,
                timeout=self.connect_timeout,
            )
        logger.info("SSH connection established to '%s'.", self.host)

    def execute(
        self,
        command: str,
        timeout: int = 30,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Execute a command and return a structured ToolResult.

        Retries up to max_retries times on transient channel errors.
        Authentication failures are NOT retried — they are permanent.

        Args:
            command:        Shell command to execute on the remote host.
            timeout:        Per-command execution timeout in seconds.
            correlation_id: Optional trace ID to link this result to a
                            LangGraph run or audit record.

        Returns:
            ToolResult with status, exit_code, stdout, stderr, duration,
            command, and correlation_id populated.
        """
        if not self.is_connected:
            return ToolResult.error(
                ResultStatus.NOT_CONNECTED,
                "SSH connection is not established.",
                command=command,
                correlation_id=correlation_id,
            )

        last_error: Exception | None = None

        for attempt in range(1 + self.max_retries):
            if attempt > 0:
                # Exponential backoff: 1s, 2s between retries.
                # WHY: Hammering a recovering SSH server makes recovery worse.
                backoff = 2 ** (attempt - 1)
                logger.warning(
                    "Retrying command (attempt %d/%d) after %ds backoff: %s",
                    attempt + 1, 1 + self.max_retries, backoff, command,
                )
                time.sleep(backoff)

            try:
                start = time.monotonic()

                with self._lock:
                    _, stdout_stream, stderr_stream = self._client.exec_command(
                        command, timeout=timeout
                    )
                    stdout = stdout_stream.read().decode(errors="replace").strip()
                    stderr = stderr_stream.read().decode(errors="replace").strip()
                    exit_code = stdout_stream.channel.recv_exit_status()

                duration = time.monotonic() - start
                status = ResultStatus.SUCCESS if exit_code == 0 else ResultStatus.FAILURE

                result = ToolResult(
                    status=status,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    duration_seconds=duration,
                    command=command,
                    correlation_id=correlation_id or "",
                )
                self._audit_log(command, result)
                return result

            except paramiko.AuthenticationException as exc:
                # Authentication failures are permanent; do not retry.
                result = ToolResult.error(
                    ResultStatus.AUTH_ERROR, str(exc),
                    command=command, correlation_id=correlation_id,
                )
                self._audit_log(command, result)
                return result

            except socket.timeout as exc:
                last_error = exc
                logger.warning("Command timed out (attempt %d): %s", attempt + 1, command)

            except Exception as exc:
                last_error = exc
                logger.warning("Command failed (attempt %d): %s — %s", attempt + 1, command, exc)

        result = ToolResult.error(
            ResultStatus.TIMEOUT if isinstance(last_error, socket.timeout)
            else ResultStatus.FAILURE,
            str(last_error),
            command=command,
            correlation_id=correlation_id,
        )
        self._audit_log(command, result)
        return result

    def disconnect(self) -> None:
        """Close the SSH connection. Safe to call if not connected."""
        with self._lock:
            if self._client:
                self._client.close()
                self._client = None
                logger.info("SSH connection to '%s' closed.", self.host)

    def __enter__(self) -> "SSHConnection":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.disconnect()
        return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Exercise SSHConnection against the host in inventory.yaml."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    inventory_path = os.path.join(
        os.path.dirname(__file__), "..", "inventory", "inventory.yaml"
    )
    try:
        inv = _load_inventory(inventory_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Could not load inventory: %s", exc)
        return

    host, login, password = inv["host"], inv["login"], inv["password"]

    print("\n--- Test 1: context manager + command execution ---")
    try:
        with SSHConnection(host=host, login=login, password=password,
                           host_key_policy=HostKeyPolicy.TRUST_ON_FIRST_USE) as conn:
            result = conn.execute("uname -a")
            print(f"  status    : {result.status.value}")
            print(f"  exit_code : {result.exit_code}")
            print(f"  duration  : {result.duration_seconds:.3f}s")
            print(f"  stdout    : {result.stdout}")
    except Exception as exc:
        logger.error("Test 1 failed: %s", exc)

    print("\n--- Test 2: manual connect / disconnect ---")
    conn = SSHConnection(host=host, login=login, password=password,
                         host_key_policy=HostKeyPolicy.TRUST_ON_FIRST_USE)
    try:
        conn.connect()
        result = conn.execute("uptime")
        print(f"  status : {result.status.value}")
        print(f"  stdout : {result.stdout}")
    except Exception as exc:
        logger.error("Test 2 failed: %s", exc)
    finally:
        conn.disconnect()

    print("\n--- Test 3: authentication failure ---")
    try:
        with SSHConnection(host=host, login=login, password="<wrong>",
                           host_key_policy=HostKeyPolicy.TRUST_ON_FIRST_USE) as conn:
            result = conn.execute("whoami")
            print(f"  status : {result.status.value}")
            assert result.status == ResultStatus.AUTH_ERROR
            print("  PASS: AUTH_ERROR returned for bad password.")
    except Exception as exc:
        logger.error("Test 3 failed unexpectedly: %s", exc)

    print("\n--- Test 4: connection timeout ---")
    try:
        with SSHConnection(host="192.0.2.1", login=login, password=password,
                           host_key_policy=HostKeyPolicy.TRUST_ON_FIRST_USE,
                           connect_timeout=3) as conn:
            conn.execute("whoami")
        print("  ERROR: expected timeout was not raised.")
    except (socket.timeout, OSError) as exc:
        print(f"  PASS: connection failed as expected — {exc}")


if __name__ == "__main__":
    main()
