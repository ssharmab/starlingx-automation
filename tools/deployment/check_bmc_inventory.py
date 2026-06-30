# SPDX-License-Identifier: Apache-2.0
"""
check_bmc_inventory.py
-------
BMC inventory discovery tool.

Why this exists:

- Provides server inventory information to agents.
- Detects whether inventory exists.
- Loads inventory from rvmc.yaml.
Filename: rvmc.yaml
"""

from __future__ import annotations

import yaml
import datetime

from tools.base import BaseTool
from pathlib import Path

from common.tool_result import ToolResult
from common.tool_request import ToolRequest
from common.tool_definition import ToolDefinition

class BmcInventoryTool(BaseTool):
    """
    Check if the BMC inventory has been provided.
    """

    def __init__(self):
        """
        init for this class
        """
        self._name = "bmc_inventory_discovery_tool"
        self._description = "Check if the BMC inventory file exists."
        self._filename = "C:/Users/ssharma3/Documents/WorkSpace/learning/agentic/inventory/rvmc.yaml"

    @property
    def definition(self) -> ToolDefinition:
        """
        Return the definition of the tool in ToolProperty.
        """
        return ToolDefinition(
            name=self._name,

            description=(
                "Checks whether a BMC inventory file exists "
                "and returns inventory information."
            ),

            input_schema={"path":"str"},

            output_schema={
                "inventory_found": "bool",
                "inventory": "dict"
            }
        )

    def execute(self,
                request: ToolRequest) -> ToolResult:
        """
        Execute the tool.
        """

        # open the file rvmc.yaml from inventory if it exists.
        # Then fill the ToolResult appropriately.

        # ToolRequest should contain the path to the inventory.

        if "path" not in request.parameters:
            return ToolResult(success=False,
                            exit_code=-1,
                            stdout="BMC Inventory Check Failed",
                            stderr="Path to inventory file or Inventory info not provided",
                            data=None,
                            error_message="Missing BMC Inventory data",
                            metadata=None,
                            duration_seconds=0.001)

        file_path = Path(request.parameters.get("path"))

        # Check if it exists AND is a file (not a folder)
        if not file_path.is_file():
            return ToolResult(success=False,
                                exit_code=-1,
                                stdout="BMC Inventory Check failed",
                                stderr="No file at Path to inventory file",
                                data=None,
                                error_message="Invalid BMC Inventory path",
                                metadata=None,
                                duration_seconds=0.001)


        with open(request.parameters.get("path")) as f:
            data = yaml.safe_load(f)
            print(f"[check_bmc_inventory] data={data}")
            expected_keys = {"bmc_address",
                             "bmc_username",
                             "bmc_password",
                             "image"}

            missing_keys = expected_keys - data.keys()

            missing_values = [key for key, val in data.items()
                              if val is None or (isinstance(val, str) and val.strip() == "")]

            if missing_keys or missing_values:
                print("missing keys or values")
                stdout_str = (f"Inventory missing these keys "
                              f"[{missing_keys}] or their values [{missing_values}]")
                return ToolResult(success=False,
                                exit_code=-1,
                                stdout=stdout_str,
                                stderr=stdout_str,
                                data=None,
                                error_message="ERROR: " + stdout_str,
                                timestamp="",
                                metadata=None,
                                duration_seconds=0.001)

            return ToolResult(
                success=True,
                exit_code=0,
                stdout="Inventory data valid.",
                stderr="",
                data=data,
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=0.01
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
    print("  BmcInventoryTool — test harness")
    print("=" * 60)

    tool = BmcInventoryTool()

    # --- Test 1: Missing path parameter ---
    print("\n--- Test 1: Missing 'path' parameter ---")
    request_no_path = ToolRequest(
        correlation_id="test-001",
        parameters={}
    )
    result = tool.execute(request_no_path)
    print(f"  success   : {result.success}")
    print(f"  exit_code : {result.exit_code}")
    print(f"  stderr    : {result.stderr}")
    assert result.success is False, "Expected failure when path is missing"
    print("  PASS")

    # --- Test 2: Non-existent file ---
    print("\n--- Test 2: Non-existent file path ---")
    request_bad_path = ToolRequest(
        correlation_id="test-002",
        parameters={"path": "/non/existent/file.yaml"}
    )

    result = tool.execute(request_bad_path)
    print(f"  success   : {result.success}")
    print(f"  exit_code : {result.exit_code}")
    print(f"  stderr    : {result.stderr}")
    assert result.success is False, "Expected failure when path is missing"
    print("  PASS")

    # --- Test 3: Valid inventory file ---
    print("\n--- Test 3: Valid inventory file (rvmc.yaml) ---")
    inventory_path = str(
        Path(__file__).parent.parent.parent / "inventory" / "rvmc.yaml"
    )
    request_valid = ToolRequest(
        correlation_id="test-003",
        parameters={"path": inventory_path}
    )
    try:
        result = tool.execute(request_valid)
        print(f"  success   : {result.success}")
        print(f"  exit_code : {result.exit_code}")
        print(f"  stdout    : {result.stdout}")
        if result.success:
            print(f"  data keys : {list(result.data.keys()) if result.data else 'None'}")
            print(f"  timestamp : {result.timestamp}")
        else:
            print(f"  error     : {result.error_message}")
        print("  PASS")
    except Exception as exc:
        print(f"  FAIL: {type(exc).__name__}: {exc}")

    # --- Test 4: Inventory with missing keys (synthetic) ---
    print("\n--- Test 4: Inventory with missing keys (synthetic) ---")
    import tempfile
    import os

    incomplete_yaml = "bmc_address: 10.0.0.1\nbmc_username: admin\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                     delete=False) as tmp:
        tmp.write(incomplete_yaml)
        tmp_path = tmp.name

    try:
        request_incomplete = ToolRequest(
            correlation_id="test-004",
            parameters={"path": tmp_path}
        )
        result = tool.execute(request_incomplete)
        print(f"  success   : {result.success}")
        print(f"  stdout    : {result.stdout}")
        assert result.success is False, "Expected failure for incomplete inventory"
        print("  PASS")
    finally:
        os.unlink(tmp_path)

    # --- Test 5: Inventory with empty values (synthetic) ---
    print("\n--- Test 5: Inventory with empty values (synthetic) ---")
    empty_val_yaml = (
        "bmc_address: 10.0.0.1\n"
        "bmc_username: admin\n"
        "bmc_password: ''\n"
        "image: http://x/boot.iso\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                     delete=False) as tmp:
        tmp.write(empty_val_yaml)
        tmp_path = tmp.name

    try:
        request_empty_val = ToolRequest(
            correlation_id="test-005",
            parameters={"path": tmp_path}
        )
        result = tool.execute(request_empty_val)
        print(f"  success   : {result.success}")
        print(f"  stdout    : {result.stdout}")
        assert result.success is False, "Expected failure for empty values"
        print("  PASS")
    finally:
        os.unlink(tmp_path)

    # --- Test 6: Tool definition ---
    print("\n--- Test 6: Tool definition property ---")
    defn = tool.definition
    print(f"  name      : {defn.name}")
    print(f"  desc      : {defn.description}")
    print(f"  in_schema : {defn.input_schema}")
    print(f"  out_schema: {defn.output_schema}")
    assert defn.name == "bmc_inventory_discovery_tool"
    print("  PASS")

    print("\n" + "=" * 60)
    print("  All BmcInventoryTool tests complete.")
    print("=" * 60)
