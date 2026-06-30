# SPDX-License-Identifier: Apache-2.0
"""
check_cluster_exists.py
-------
Cluster Existence check tool.

Why this exists:

- Provides information on whether there is an existing cluster to agents.
- Connects to the cluster via SSH using host, login, and password.
- Returns success if the SSH connection is established.
"""

from __future__ import annotations

import datetime
import ipaddress
import paramiko

from tools.base import BaseTool

from common.tool_result import ToolResult
from common.tool_request import ToolRequest
from common.tool_definition import ToolDefinition

from utils.ssh_connection import SSHConnection, HostKeyPolicy


class ClusterConnectivityCheckTool(BaseTool):
    """
    Check if a cluster exists by attempting an SSH connection
    to the floating IP address.
    """

    def __init__(self):
        self._name = "cluster_connectivity_check_tool"
        self._description = "Check if the cluster can be connected to over SSH"

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,

            description=(
                "Checks whether a given cluster exists by SSH-connecting "
                "to its floating IP address. Returns cluster_exists: true "
                "if the connection succeeds."
            ),

            input_schema={
                "host": "str — floating IP address of the cluster",
                "login": "str — SSH username",
                "password": "str — SSH password",
            },

            output_schema={
                "cluster_exists": "bool",
                "cluster_info": "dict",
            }
        )

    def _validate_ip_address(self, ip_addr: str) -> bool:
        """Check if the provided string is a valid IP address."""
        try:
            ipaddress.ip_address(ip_addr)
            return True
        except ValueError:
            return False

    def execute(self, request: ToolRequest) -> ToolResult:
        """
        Execute the tool.

        Expects request.parameters to contain:
            - host: floating IP address of the cluster
            - login: SSH username
            - password: SSH password

        Returns ToolResult with success=True if the SSH connection succeeds.
        """
        start_time = datetime.datetime.now()

        # --- Validate required parameters ---

        if "host" not in request.parameters:
            return ToolResult(
                success=False,
                exit_code=-3,
                stdout="Missing floating IP address of cluster",
                stderr="Missing 'host' parameter",
                data=request.parameters,
                error_message="Missing 'host' parameter",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=0.01,
            )

        host = request.parameters["host"].strip()

        if not self._validate_ip_address(host):
            return ToolResult(
                success=False,
                exit_code=-3,
                stdout="Invalid IP address",
                stderr=f"'{host}' is not a valid IP address",
                data=request.parameters,
                error_message=f"Invalid IP address: {host}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=0.01,
            )

        if "login" not in request.parameters:
            return ToolResult(
                success=False,
                exit_code=-3,
                stdout="Missing login",
                stderr="Missing 'login' parameter",
                data=request.parameters,
                error_message="Missing 'login' parameter",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=0.01,
            )

        if "password" not in request.parameters:
            return ToolResult(
                success=False,
                exit_code=-3,
                stdout="Missing password",
                stderr="Missing 'password' parameter",
                data=request.parameters,
                error_message="Missing 'password' parameter",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=0.01,
            )

        login = request.parameters["login"]
        password = request.parameters["password"]

        # --- Attempt SSH connection ---
        conn = None
        try:
            conn = SSHConnection(
                host=host,
                login=login,
                password=password,
                host_key_policy=HostKeyPolicy.TRUST_ON_FIRST_USE,
                connect_timeout=10,
            )
            conn.connect()

        except TimeoutError as exc:
            print("[ClusterExistenceChecktool] Timeout")
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=1,
                stdout="Cluster connection timed out",
                stderr=f"Timeout connecting to {host}: {exc}",
                data={"cluster_exists": False, "host": host, "error_type": "timeout"} | request.parameters,
                error_message=f"SSH connection timed out: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        except ConnectionRefusedError as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=1,
                stdout="Cluster connection refused",
                stderr=f"Connection refused by {host}: {exc}",
                data={"cluster_exists": False, "host": host, "error_type": "connection_refused"} | request.parameters,
                error_message=f"SSH port not open or service not running: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        except ConnectionAbortedError as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=1,
                stdout="Host key verification failed",
                stderr=f"Host key policy violation for {host}: {exc}",
                data={"cluster_exists": False, "host": host, "error_type": "host_key_rejected"} | request.parameters,
                error_message=f"Host key verification failed: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        except paramiko.AuthenticationException as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=2,
                stdout="Authentication failed",
                stderr=f"Invalid credentials for {login}@{host}: {exc}",
                data={"cluster_exists": False, "host": host, "error_type": "auth_failed"} | request.parameters,
                error_message=f"SSH authentication failed: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        except OSError as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=1,
                stdout="Network error",
                stderr=f"Cannot reach {host}: {exc}",
                data={"cluster_exists": False, "host": host, "error_type": "network_error"} | request.parameters,
                error_message=f"Network error connecting to {host}: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        except Exception as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=1,
                stdout="Unexpected connection error",
                stderr=f"Unexpected error connecting to {host}: {type(exc).__name__}: {exc}",
                data={"cluster_exists": False, "host": host, "error_type": "unexpected"} | request.parameters,
                error_message=f"Unexpected SSH error: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        # Connection succeeded — cluster exists
        conn.disconnect()
        elapsed = (datetime.datetime.now() - start_time).total_seconds()

        return ToolResult(
            success=True,
            exit_code=0,
            stdout=f"Cluster at {host} is reachable via SSH",
            stderr="",
            data={"cluster_exists": True, "host": host} | request.parameters,
            timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            metadata=None,
            duration_seconds=elapsed,
        )


# ---------------------------------------------------------------------------
# __main__ test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path
    from unittest.mock import patch, MagicMock

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    import paramiko as _paramiko

    print("=" * 60)
    print("  ClusterExistenceCheckTool — test harness")
    print("=" * 60)

    tool = ClusterExistenceCheckTool()

    # =========================================================================
    # Test 1: Missing 'host' parameter
    # =========================================================================
    print("\n--- Test 1: Missing 'host' parameter ---")
    result = tool.execute(ToolRequest(correlation_id="t1", parameters={}))
    print(f"  data: {result.data}")
    print(f"  success: {result.success}")
    print(f"  stderr : {result.stderr}")
    assert result.success is False
    assert "host" in result.stderr.lower()
    print("  PASS")

    # =========================================================================
    # Test 2: Invalid IP address
    # =========================================================================
    print("\n--- Test 2: Invalid IP address ---")
    result = tool.execute(ToolRequest(
        correlation_id="t2",
        parameters={"host": "not.an.ip", "login": "x", "password": "y"}
    ))
    print(f"  data: {result.data}")
    print(f"  success: {result.success}")
    print(f"  stderr : {result.stderr}")
    assert result.success is False
    assert "not a valid" in result.stderr.lower() or "invalid" in result.stderr.lower()
    print("  PASS")

    # =========================================================================
    # Test 3: Missing 'login' parameter
    # =========================================================================
    print("\n--- Test 3: Missing 'login' parameter ---")
    result = tool.execute(ToolRequest(
        correlation_id="t3",
        parameters={"host": "10.0.0.1"}
    ))
    print(f"  data: {result.data}")
    print(f"  success: {result.success}")
    print(f"  stderr : {result.stderr}")
    assert result.success is False
    assert "login" in result.stderr.lower()
    print("  PASS")

    # =========================================================================
    # Test 4: Missing 'password' parameter
    # =========================================================================
    print("\n--- Test 4: Missing 'password' parameter ---")
    result = tool.execute(ToolRequest(
        correlation_id="t4",
        parameters={"host": "10.0.0.1", "login": "admin"}
    ))
    print(f"  data: {result.data}")
    print(f"  success: {result.success}")
    print(f"  stderr : {result.stderr}")
    assert result.success is False
    assert "password" in result.stderr.lower()
    print("  PASS")

    # =========================================================================
    # Test 5: Empty host (whitespace only)
    # =========================================================================
    print("\n--- Test 5: Empty host (whitespace only) ---")
    result = tool.execute(ToolRequest(
        correlation_id="t5",
        parameters={"host": "   ", "login": "admin", "password": "pass"}
    ))
    print(f"  data: {result.data}")
    print(f"  success: {result.success}")
    print(f"  stderr : {result.stderr}")
    assert result.success is False
    print("  PASS")

    # =========================================================================
    # Test 6: Timeout error (mocked)
    # =========================================================================
    print("\n--- Test 6: SSH timeout (mocked) ---")
    with patch("__main__.SSHConnection") as MockConn:
        mock_instance = MagicMock()
        mock_instance.connect.side_effect = TimeoutError("timed out after 10s")
        MockConn.return_value = mock_instance

        result = tool.execute(ToolRequest(
            correlation_id="t6",
            parameters={"host": "10.0.0.1", "login": "admin", "password": "pass"}
        ))
        print(f"  data: {result.data}")
        print(f"  success   : {result.success}")
        print(f"  stderr    : {result.stderr}")
        print(f"  error_type: {result.data.get('error_type')}")
        assert result.success is False
        assert result.data["error_type"] == "timeout"
        print("  PASS")

    # =========================================================================
    # Test 7: Connection refused (mocked)
    # =========================================================================
    print("\n--- Test 7: Connection refused (mocked) ---")
    with patch("__main__.SSHConnection") as MockConn:
        mock_instance = MagicMock()
        mock_instance.connect.side_effect = ConnectionRefusedError("refused")
        MockConn.return_value = mock_instance

        result = tool.execute(ToolRequest(
            correlation_id="t7",
            parameters={"host": "10.0.0.1", "login": "admin", "password": "pass"}
        ))
        print(f"  data: {result.data}")
        print(f"  success   : {result.success}")
        print(f"  stderr    : {result.stderr}")
        print(f"  error_type: {result.data.get('error_type')}")
        assert result.success is False
        assert result.data["error_type"] == "connection_refused"
        print("  PASS")

    # =========================================================================
    # Test 8: Host key rejected (mocked)
    # =========================================================================
    print("\n--- Test 8: Host key rejected (mocked) ---")
    with patch("__main__.SSHConnection") as MockConn:
        mock_instance = MagicMock()
        mock_instance.connect.side_effect = ConnectionAbortedError("not in known_hosts")
        MockConn.return_value = mock_instance

        result = tool.execute(ToolRequest(
            correlation_id="t8",
            parameters={"host": "10.0.0.1", "login": "admin", "password": "pass"}
        ))
        print(f"  data: {result.data}")
        print(f"  success   : {result.success}")
        print(f"  stderr    : {result.stderr}")
        print(f"  error_type: {result.data.get('error_type')}")
        assert result.success is False
        assert result.data["error_type"] == "host_key_rejected"
        print("  PASS")

    # =========================================================================
    # Test 9: Authentication failure (mocked)
    # =========================================================================
    print("\n--- Test 9: Authentication failure (mocked) ---")
    with patch("__main__.SSHConnection") as MockConn:
        mock_instance = MagicMock()
        mock_instance.connect.side_effect = _paramiko.AuthenticationException("bad creds")
        MockConn.return_value = mock_instance

        result = tool.execute(ToolRequest(
            correlation_id="t9",
            parameters={"host": "10.0.0.1", "login": "admin", "password": "wrong"}
        ))
        print(f"  data: {result.data}")
        print(f"  success   : {result.success}")
        print(f"  stderr    : {result.stderr}")
        print(f"  error_type: {result.data.get('error_type')}")
        print(f"  exit_code : {result.exit_code}")
        assert result.success is False
        assert result.data["error_type"] == "auth_failed"
        assert result.exit_code == 2
        print("  PASS")

    # =========================================================================
    # Test 10: Network/OS error (mocked)
    # =========================================================================
    print("\n--- Test 10: Network unreachable (mocked) ---")
    with patch("__main__.SSHConnection") as MockConn:
        mock_instance = MagicMock()
        mock_instance.connect.side_effect = OSError("Network is unreachable")
        MockConn.return_value = mock_instance

        result = tool.execute(ToolRequest(
            correlation_id="t10",
            parameters={"host": "10.0.0.1", "login": "admin", "password": "pass"}
        ))
        print(f"  data: {result.data}")
        print(f"  success   : {result.success}")
        print(f"  stderr    : {result.stderr}")
        print(f"  error_type: {result.data.get('error_type')}")
        assert result.success is False
        assert result.data["error_type"] == "network_error"
        print("  PASS")

    # =========================================================================
    # Test 11: Unexpected error (mocked)
    # =========================================================================
    print("\n--- Test 11: Unexpected error (mocked) ---")
    with patch("__main__.SSHConnection") as MockConn:
        mock_instance = MagicMock()
        mock_instance.connect.side_effect = RuntimeError("something bizarre")
        MockConn.return_value = mock_instance

        result = tool.execute(ToolRequest(
            correlation_id="t11",
            parameters={"host": "10.0.0.1", "login": "admin", "password": "pass"}
        ))
        print(f"  data: {result.data}")
        print(f"  success   : {result.success}")
        print(f"  stderr    : {result.stderr}")
        print(f"  error_type: {result.data.get('error_type')}")
        assert result.success is False
        assert result.data["error_type"] == "unexpected"
        assert "RuntimeError" in result.stderr
        print("  PASS")

    # =========================================================================
    # Test 12: Successful connection (mocked)
    # =========================================================================
    print("\n--- Test 12: Successful SSH connection (mocked) ---")
    with patch("__main__.SSHConnection") as MockConn:
        mock_instance = MagicMock()
        mock_instance.connect.return_value = None  # no exception = success
        mock_instance.disconnect.return_value = None
        MockConn.return_value = mock_instance

        result = tool.execute(ToolRequest(
            correlation_id="t12",
            parameters={"host": "10.0.0.1", "login": "admin", "password": "pass"}
        ))
        print(f"  data: {result.data}")
        print(f"  success   : {result.success}")
        print(f"  stdout    : {result.stdout}")
        print(f"  data      : {result.data}")
        assert result.success is True
        assert result.data["cluster_exists"] is True
        assert result.data["host"] == "10.0.0.1"
        mock_instance.disconnect.assert_called_once()
        print("  PASS")

    # =========================================================================
    # Test 13: Tool definition
    # =========================================================================
    print("\n--- Test 13: Tool definition ---")
    defn = tool.definition
    print(f"  data: {result.data}")
    print(f"  name       : {defn.name}")
    print(f"  description: {defn.description}")
    print(f"  in_schema  : {defn.input_schema}")
    print(f"  out_schema : {defn.output_schema}")
    assert defn.name == "cluster_existence_check_tool"
    assert "host" in defn.input_schema
    assert "login" in defn.input_schema
    assert "password" in defn.input_schema
    print("  PASS")

    # =========================================================================
    # Test 14: IPv6 address accepted
    # =========================================================================
    print("\n--- Test 14: Valid IPv6 address (mocked connection) ---")
    with patch("__main__.SSHConnection") as MockConn:
        mock_instance = MagicMock()
        mock_instance.connect.return_value = None
        mock_instance.disconnect.return_value = None
        MockConn.return_value = mock_instance

        result = tool.execute(ToolRequest(
            correlation_id="t14",
            parameters={"host": "::1", "login": "admin", "password": "pass"}
        ))
        print(f"  data: {result.data}")
        print(f"  success: {result.success}")
        print(f"  data   : {result.data}")
        assert result.success is True
        assert result.data["host"] == "::1"
        print("  PASS")

    print("\n" + "=" * 60)
    print("  All ClusterExistenceCheckTool tests complete. (14/14)")
    print("=" * 60)
