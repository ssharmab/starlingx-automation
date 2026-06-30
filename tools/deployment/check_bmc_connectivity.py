# SPDX-License-Identifier: Apache-2.0
"""
check_bmc_connectivity.py
-------
BMC inventory connectivity tool.

Why this exists:

- Verifies that the BMC is reachable over the network.
- Pings the BMC address 3 times and requires all 3 to succeed.
- Uses the same ping logic as rvmc.py's _redfish_client_connect().
"""

from __future__ import annotations

import os
import sys
import socket
import datetime

from tools.base import BaseTool

from common.tool_result import ToolResult
from common.tool_request import ToolRequest
from common.tool_definition import ToolDefinition


def _is_ipv6(address: str) -> bool:
    """Check if an address is IPv6."""
    try:
        socket.inet_pton(socket.AF_INET6, address)
        return True
    except socket.error:
        return False


def _ping_once(address: str) -> bool:
    """
    Ping the given address once.
    Returns True if the ping succeeds (exit code 0).
    """
    ping_count_flag = "-n 1" if sys.platform == "win32" else "-c 1"
    ping_null = "NUL" if sys.platform == "win32" else "/dev/null"

    if _is_ipv6(address):
        cmd = "ping -6 %s %s > %s 2>&1" % (ping_count_flag, address, ping_null)
    else:
        cmd = "ping %s %s > %s 2>&1" % (ping_count_flag, address, ping_null)

    rc = os.system(cmd)
    return rc == 0


class BmcInventoryConnectivityCheckTool(BaseTool):
    """
    Check if the BMC is reachable by pinging it 3 times.
    All 3 pings must succeed for the check to pass.
    """

    def __init__(self):
        self._name = "bmc_connectivity_check_tool"
        self._description = "Ping the BMC address 3 times to verify network connectivity."

    @property
    def definition(self) -> ToolDefinition:
        """Return the tool definition."""
        return ToolDefinition(
            name=self._name,

            description=(
                "Pings the BMC address 3 times. "
                "All 3 must succeed for a pass. "
                "Fails with 'BMC not accessible' if any ping fails."
            ),

            input_schema={
                "bmc_address": "str"
            },

            output_schema={
                "reachable": "bool",
                "pings_sent": "int",
                "pings_received": "int",
            }
        )

    def execute(self, request: ToolRequest) -> ToolResult:
        """
        Execute the connectivity check.

        Expects request.parameters["bmc_address"] to contain the BMC IP/hostname.
        """
        start_time = datetime.datetime.now()

        if "bmc_address" not in request.parameters:
            return ToolResult(
                success=False,
                exit_code=-1,
                stdout="BMC Connectivity Check Failed",
                stderr="bmc_address not provided in parameters",
                data=None,
                error_message="Missing bmc_address parameter",
                metadata=None,
                duration_seconds=0.001,
            )

        bmc_address = request.parameters["bmc_address"].strip()

        if not bmc_address:
            return ToolResult(
                success=False,
                exit_code=-1,
                stdout="BMC Connectivity Check Failed",
                stderr="bmc_address is empty",
                data=None,
                error_message="Empty bmc_address parameter",
                metadata=None,
                duration_seconds=0.001,
            )

        pings_sent = 3
        pings_received = 0
        failed_attempts = []

        for attempt in range(1, pings_sent + 1):
            if _ping_once(bmc_address):
                pings_received += 1
            else:
                failed_attempts.append(attempt)

        elapsed = (datetime.datetime.now() - start_time).total_seconds()

        if pings_received == pings_sent:
            return ToolResult(
                success=True,
                exit_code=0,
                stdout=f"BMC at {bmc_address} is reachable ({pings_received}/{pings_sent} pings OK)",
                stderr="",
                data={
                    "reachable": True,
                    "pings_sent": pings_sent,
                    "pings_received": pings_received,
                    "bmc_address": bmc_address,
                },
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )
        else:
            return ToolResult(
                success=False,
                exit_code=1,
                stdout=f"BMC Connectivity Check Failed ({pings_received}/{pings_sent} pings OK)",
                stderr="BMC not accessible",
                data={
                    "reachable": False,
                    "pings_sent": pings_sent,
                    "pings_received": pings_received,
                    "bmc_address": bmc_address,
                    "failed_attempts": failed_attempts,
                },
                error_message=f"BMC not accessible at {bmc_address} — "
                              f"only {pings_received}/{pings_sent} pings succeeded",
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

    # Ensure project root is importable
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    print("=" * 60)
    print("  BmcInventoryConnectivityTool — test harness")
    print("=" * 60)

    tool = BmcInventoryConnectivityTool()

    # --- Test 1: Missing bmc_address parameter ---
    print("\n--- Test 1: Missing 'bmc_address' parameter ---")
    request_no_addr = ToolRequest(
        correlation_id="test-001",
        parameters={}
    )
    result = tool.execute(request_no_addr)
    print(f"  success   : {result.success}")
    print(f"  stderr    : {result.stderr}")
    assert result.success is False, "Expected failure when bmc_address is missing"
    print("  PASS")

    # --- Test 2: Empty bmc_address ---
    print("\n--- Test 2: Empty bmc_address ---")
    request_empty = ToolRequest(
        correlation_id="test-002",
        parameters={"bmc_address": "  "}
    )
    result = tool.execute(request_empty)
    print(f"  success   : {result.success}")
    print(f"  stderr    : {result.stderr}")
    assert result.success is False, "Expected failure when bmc_address is empty"
    print("  PASS")

    # --- Test 3: Ping localhost (should pass) ---
    print("\n--- Test 3: Ping localhost ---")
    request_localhost = ToolRequest(
        correlation_id="test-003",
        parameters={"bmc_address": "127.0.0.1"}
    )
    result = tool.execute(request_localhost)
    print(f"  success   : {result.success}")
    print(f"  stdout    : {result.stdout}")
    print(f"  data      : {result.data}")
    print(f"  duration  : {result.duration_seconds:.3f}s")
    assert result.success is True, "Expected success pinging localhost"
    print("  PASS")

    # --- Test 4: Ping unreachable address (should fail) ---
    print("\n--- Test 4: Ping unreachable address ---")
    request_unreachable = ToolRequest(
        correlation_id="test-004",
        parameters={"bmc_address": "192.0.2.1"}  # TEST-NET, should be unreachable
    )
    result = tool.execute(request_unreachable)
    print(f"  success   : {result.success}")
    print(f"  stdout    : {result.stdout}")
    print(f"  stderr    : {result.stderr}")
    print(f"  data      : {result.data}")
    print(f"  duration  : {result.duration_seconds:.3f}s")
    assert result.success is False, "Expected failure pinging unreachable address"
    assert result.stderr == "BMC not accessible"
    print("  PASS")

    # --- Test 5: Tool definition ---
    print("\n--- Test 5: Tool definition property ---")
    defn = tool.definition
    print(f"  name      : {defn.name}")
    print(f"  desc      : {defn.description}")
    print(f"  in_schema : {defn.input_schema}")
    print(f"  out_schema: {defn.output_schema}")
    assert defn.name == "bmc_connectivity_check_tool"
    print("  PASS")

    print("\n" + "=" * 60)
    print("  All BmcInventoryConnectivityTool tests complete.")
    print("=" * 60)
