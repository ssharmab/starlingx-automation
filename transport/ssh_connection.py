# SPDX-License-Identifier: Apache-2.0
"""
ssh_connection.py
----------------------------

Agent-ready SSH transport.

Major changes from the original implementation:

1. Removed interactive input() prompts.
   Agents cannot respond to terminal prompts.

2. Removed print() statements.
   Libraries return data; callers decide how to display it.

3. Added ToolResult return objects.
   Structured outputs are mandatory for agent workflows.

4. Added command timeout support.
   Prevents hanging agents.

5. Added exit-code capture.
   Agents need deterministic success/failure signals.

6. Added execution duration metrics.
   Important for observability and auditing.

7. Added explicit HostKeyPolicy.
   Replaces interactive trust decisions.

8. Added audit logging.
   Records host, command, duration, and exit status.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import time
from enum import Enum

import paramiko

from common.tool_result import ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inventory loader
# ---------------------------------------------------------------------------

def _load_inventory(path: str) -> dict:
    """
    Load host credentials from the inventory YAML file.

    Args:
        path: Path to the inventory YAML file.

    Returns:
        Parsed inventory dictionary.

    Raises:
        FileNotFoundError: If the inventory file does not exist.
        ValueError:        If required keys are missing.
    """
    import yaml
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Inventory file not found: '{path}'.")
    with open(path) as fh:
        data = yaml.safe_load(fh)
    missing = [k for k in ("host", "login", "password") if k not in data]
    if missing:
        raise ValueError(f"Inventory is missing keys: {missing}.")
    return data


class HostKeyPolicy(str, Enum):
    """
    Agent-friendly host key policies.

    STRICT:
        Host must already exist in known_hosts.

    TRUST_ON_FIRST_USE:
        Unknown host keys are automatically persisted.
        Similar to OpenSSH's TOFU model.
    """
    STRICT = "STRICT"
    TRUST_ON_FIRST_USE = "TRUST_ON_FIRST_USE"


class SSHConnection:
    def __init__(
        self,
        host: str,
        login: str,
        password: str,
        port: int = 22,
        host_key_policy: HostKeyPolicy = HostKeyPolicy.STRICT,
        connect_timeout: int = 10,
    ) -> None:

        self.host = host
        self.login = login
        self.password = password
        self.port = port
        self.host_key_policy = host_key_policy
        self.connect_timeout = connect_timeout

        self._client: paramiko.SSHClient | None = None
        self.ip_version = self._detect_ip_version(host)

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
        ssh_dir = os.path.dirname(known_hosts)

        os.makedirs(ssh_dir, mode=0o700, exist_ok=True)

        host_keys = paramiko.HostKeys()
        if os.path.isfile(known_hosts):
            host_keys.load(known_hosts)

        host_keys.add(self.host, host_key.get_name(), host_key)
        host_keys.save(known_hosts)

    def connect(self) -> None:
        logger.info("Connecting to %s", self.host)

        sock = socket.socket(self._get_socket_family(), socket.SOCK_STREAM)
        sock.settimeout(self.connect_timeout)
        sock.connect((self.host, self.port))

        known_hosts = self._known_hosts_path()

        host_keys = paramiko.HostKeys()
        if os.path.isfile(known_hosts):
            host_keys.load(known_hosts)

        if host_keys.lookup(self.host) is None:
            if self.host_key_policy == HostKeyPolicy.STRICT:
                raise ConnectionAbortedError(
                    f"{self.host} not present in known_hosts."
                )

            if self.host_key_policy == HostKeyPolicy.TRUST_ON_FIRST_USE:
                remote_key = self._fetch_remote_host_key(sock)
                self._persist_host_key(remote_key)

                sock = socket.socket(
                    self._get_socket_family(),
                    socket.SOCK_STREAM,
                )
                sock.settimeout(self.connect_timeout)
                sock.connect((self.host, self.port))

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

    def execute(
        self,
        command: str,
        timeout: int = 30,
    ) -> ToolResult:
        """
        Agent-safe execution API.

        Returns ToolResult instead of raw tuples.

        NOTE:
        This is still a transport-layer method.
        Higher-level agent tools should wrap this method and expose
        specific operations such as:

            get_nodes()
            get_pods()
            get_events()

        instead of allowing arbitrary LLM-generated commands.
        """

        if self._client is None:
            raise RuntimeError("SSH connection is not established.")

        start = time.monotonic()

        logger.info(
            "SSH_EXEC host=%s command=%s",
            self.host,
            command,
        )

        stdin, stdout_stream, stderr_stream = self._client.exec_command(
            command,
            timeout=timeout,
        )

        exit_code = stdout_stream.channel.recv_exit_status()

        stdout = stdout_stream.read().decode(errors="replace")
        stderr = stderr_stream.read().decode(errors="replace")

        duration = time.monotonic() - start

        logger.info(
            "SSH_RESULT host=%s exit_code=%s duration=%.3f",
            self.host,
            exit_code,
            duration,
        )

        return ToolResult(
            success=(exit_code == 0),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
        )

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

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
    """
    Exercise SSHConnection against the host defined in inventory.yaml.

    Tests performed:
      1. Context-manager connection — verifies connect/disconnect lifecycle.
      2. Command execution — runs a harmless command and prints the ToolResult.
      3. Manual connect/disconnect — verifies the explicit API works correctly.
      4. Authentication failure — confirms AuthenticationException is raised
         when wrong credentials are supplied.
      5. Timeout — confirms socket.timeout is raised for an unreachable host.
    """
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

    host     = inv["host"]
    login    = inv["login"]
    password = inv["password"]

    # ------------------------------------------------------------------
    # Test 1: context-manager lifecycle + command execution
    # ------------------------------------------------------------------
    print("\n--- Test 1: context manager + command execution ---")
    try:
        with SSHConnection(
            host=host,
            login=login,
            password=password,
            host_key_policy=HostKeyPolicy.TRUST_ON_FIRST_USE,
        ) as conn:
            result: ToolResult = conn.execute("uname -a")
            print(f"  success      : {result.success}")
            print(f"  exit_code    : {result.exit_code}")
            print(f"  duration     : {result.duration_seconds:.3f}s")
            print(f"  stdout       : {result.stdout.strip()}")
            if result.stderr.strip():
                print(f"  stderr       : {result.stderr.strip()}")
    except Exception as exc:
        logger.error("Test 1 failed: %s", exc)

    # ------------------------------------------------------------------
    # Test 2: manual connect / disconnect
    # ------------------------------------------------------------------
    print("\n--- Test 2: manual connect / disconnect ---")
    conn = SSHConnection(
        host=host,
        login=login,
        password=password,
        host_key_policy=HostKeyPolicy.TRUST_ON_FIRST_USE,
    )
    try:
        conn.connect()
        result = conn.execute("uptime")
        print(f"  success      : {result.success}")
        print(f"  stdout       : {result.stdout.strip()}")
    except Exception as exc:
        logger.error("Test 2 failed: %s", exc)
    finally:
        conn.disconnect()
        print("  disconnected.")

    # ------------------------------------------------------------------
    # Test 3: authentication failure
    # ------------------------------------------------------------------
    print("\n--- Test 3: authentication failure ---")
    try:
        with SSHConnection(
            host=host,
            login=login,
            password="<wrong_password>",
            host_key_policy=HostKeyPolicy.TRUST_ON_FIRST_USE,
        ) as conn:
            conn.execute("whoami")
        print("  ERROR: expected AuthenticationException was not raised.")
    except paramiko.AuthenticationException:
        print("  PASS: AuthenticationException raised for bad password.")
    except Exception as exc:
        logger.error("Test 3 unexpected exception: %s", exc)

    # ------------------------------------------------------------------
    # Test 4: connection timeout (unreachable host)
    # ------------------------------------------------------------------
    print("\n--- Test 4: connection timeout ---")
    try:
        with SSHConnection(
            host="192.0.2.1",   # RFC 5737 documentation address — guaranteed unreachable
            login=login,
            password=password,
            host_key_policy=HostKeyPolicy.TRUST_ON_FIRST_USE,
            connect_timeout=3,
        ) as conn:
            conn.execute("whoami")
        print("  ERROR: expected timeout was not raised.")
    except (socket.timeout, OSError) as exc:
        print(f"  PASS: connection failed as expected — {exc}")
    except Exception as exc:
        logger.error("Test 4 unexpected exception: %s", exc)


if __name__ == "__main__":
    main()
