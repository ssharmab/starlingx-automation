# SPDX-License-Identifier: Apache-2.0
"""
wrcp_rvmc_install_base.py
-------------------------
Tool that performs a base OS installation via Redfish Virtual Media Controller.

Why this exists:

- Connects to a BMC using Redfish and injects an ISO image.
- Boots the host from the ISO to perform a base OS install.
- Uses the VmcObject class from tools/rvmc/rvmc.py.
- Returns success once the power-on stage is completed.

Expected ToolRequest parameters (same fields as rvmc.yaml / check_bmc_inventory):
    - bmc_address:  IP address of the BMC
    - bmc_username: BMC login username
    - bmc_password: Base64-encoded BMC password
    - image:        HTTP/HTTPS URL of the ISO to inject
    - target_name:  (optional) human-readable label for this target
    - debug:        (optional) debug verbosity 0-4, default 0
"""

from __future__ import annotations

import datetime

from tools.base import BaseTool

from common.tool_result import ToolResult
from common.tool_request import ToolRequest
from common.tool_definition import ToolDefinition

from tools.rvmc.bmc_target import BmcTarget
from tools.rvmc.rvmc import VmcObject
from tools.rvmc.rvmc_errors import (
    RvmcError,
    RvmcAuthError,
    RvmcConnectionError,
    RvmcMediaError,
    RvmcPowerError,
    RvmcBootError,
)


class WrcpRvmcInstallBaseTool(BaseTool):
    """
    Perform a base OS installation on a host via Redfish Virtual Media.

    Uses VmcObject to:
    1. Connect to the BMC
    2. Create a Redfish session
    3. Eject any existing image
    4. Power off the host
    5. Insert the ISO image
    6. Set boot override to CD/DVD
    7. Power on the host

    Returns success=True once the host is powered on with the ISO.
    """

    def __init__(self):
        self._name = "wrcp_rvmc_install_base_tool"
        self._description = "Install base OS via Redfish Virtual Media Controller."

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,

            description=(
                "Connects to the BMC via Redfish, injects an ISO image "
                "into the virtual media drive, and boots the host from it. "
                "Returns success once the host is powered on."
            ),

            input_schema={
                "bmc_address": "str — BMC IP address",
                "bmc_username": "str — BMC login username",
                "bmc_password": "str — Base64-encoded BMC password",
                "image": "str — HTTP/HTTPS URL of the ISO image",
                "target_name": "str (optional) — human-readable label",
                "debug": "int (optional) — verbosity 0-4, default 0",
            },

            output_schema={
                "installed": "bool",
                "target": "str",
                "address": "str",
                "image": "str",
            }
        )

    def execute(self, request: ToolRequest) -> ToolResult:
        """
        Execute the RVMC install pipeline.

        Expects request.parameters to contain:
            - bmc_address
            - bmc_username
            - bmc_password (base64-encoded)
            - image
        """
        start_time = datetime.datetime.now()

        # --- Validate required parameters ---

        required_keys = ["bmc_address", "bmc_username", "bmc_password", "image"]
        missing = [k for k in required_keys if k not in request.parameters]

        if missing:
            return ToolResult(
                success=False,
                exit_code=-3,
                stdout="RVMC Install Failed — missing parameters",
                stderr=f"Missing required parameters: {missing}",
                data=None,
                error_message=f"Missing parameters: {missing}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=0.01,
            )

        # --- Build BmcTarget ---

        try:
            target = BmcTarget.from_config(
                target_name=request.parameters.get("target_name"),
                cfg={
                    "bmc_address": request.parameters["bmc_address"],
                    "bmc_username": request.parameters["bmc_username"],
                    "bmc_password": request.parameters["bmc_password"],
                    "image": request.parameters["image"],
                },
                debug=request.parameters.get("debug", 0),
            )
        except ValueError as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=-3,
                stdout="RVMC Install Failed — invalid parameters",
                stderr=f"Parameter validation error: {exc}",
                data=None,
                error_message=f"Invalid BMC parameters: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        # --- Execute the RVMC pipeline ---

        try:
            with VmcObject(target) as vmc:
                vmc.execute(request)

        except RvmcAuthError as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=2,
                stdout="RVMC Install Failed — authentication error",
                stderr=f"BMC authentication failed: {exc}",
                data={
                    "installed": False,
                    "address": target.address,
                    "error_type": "auth_failed",
                },
                error_message=f"BMC auth error: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        except RvmcConnectionError as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=1,
                stdout="RVMC Install Failed — connection error",
                stderr=f"Cannot connect to BMC at {target.address}: {exc}",
                data={
                    "installed": False,
                    "address": target.address,
                    "error_type": "connection_failed",
                },
                error_message=f"BMC connection error: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        except RvmcMediaError as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=1,
                stdout="RVMC Install Failed — virtual media error",
                stderr=f"Virtual media operation failed: {exc}",
                data={
                    "installed": False,
                    "address": target.address,
                    "error_type": "media_error",
                },
                error_message=f"Virtual media error: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        except RvmcBootError as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=1,
                stdout="RVMC Install Failed — boot override error",
                stderr=f"Boot override configuration failed: {exc}",
                data={
                    "installed": False,
                    "address": target.address,
                    "error_type": "boot_error",
                },
                error_message=f"Boot override error: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        except RvmcPowerError as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=1,
                stdout="RVMC Install Failed — power control error",
                stderr=f"Power control failed: {exc}",
                data={
                    "installed": False,
                    "address": target.address,
                    "error_type": "power_error",
                },
                error_message=f"Power control error: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        except RvmcError as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=1,
                stdout="RVMC Install Failed",
                stderr=f"RVMC error: {exc}",
                data={
                    "installed": False,
                    "address": target.address,
                    "error_type": "rvmc_error",
                },
                error_message=f"RVMC error: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        except Exception as exc:
            elapsed = (datetime.datetime.now() - start_time).total_seconds()
            return ToolResult(
                success=False,
                exit_code=1,
                stdout="RVMC Install Failed — unexpected error",
                stderr=f"Unexpected error: {type(exc).__name__}: {exc}",
                data={
                    "installed": False,
                    "address": target.address,
                    "error_type": "unexpected",
                },
                error_message=f"Unexpected error: {exc}",
                timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                metadata=None,
                duration_seconds=elapsed,
            )

        # --- Success: host is powered on with ISO ---
        elapsed = (datetime.datetime.now() - start_time).total_seconds()

        return ToolResult(
            success=True,
            exit_code=0,
            stdout=f"RVMC Install complete — host {target.address} powered on with ISO",
            stderr="",
            data={
                "installed": True,
                "target": target.target_name or target.address,
                "address": target.address,
                "image": target.image,
            },
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

    print("=" * 60)
    print("  WrcpRvmcInstallBaseTool — test harness")
    print("=" * 60)

    tool = WrcpRvmcInstallBaseTool()

    VALID_PARAMS = {
        "bmc_address": "10.0.0.1",
        "bmc_username": "ADMIN",
        "bmc_password": "cGFzc3dvcmQ=",  # base64("password")
        "image": "http://example.com/boot.iso",
    }

    # =========================================================================
    # Test 1: Missing parameters
    # =========================================================================
    print("\n--- Test 1: Missing required parameters ---")
    result = tool.execute(ToolRequest(correlation_id="t1", parameters={}))
    print(f"  success: {result.success}")
    print(f"  stderr : {result.stderr}")
    assert result.success is False
    assert "Missing" in result.stderr
    print("  PASS")

    # =========================================================================
    # Test 2: Invalid bmc_password (not valid base64)
    # =========================================================================
    print("\n--- Test 2: Invalid bmc_password ---")
    bad_params = {**VALID_PARAMS, "bmc_password": "!!!not-base64!!!"}
    result = tool.execute(ToolRequest(correlation_id="t2", parameters=bad_params))
    print(f"  success: {result.success}")
    print(f"  stderr : {result.stderr}")
    assert result.success is False
    assert "validation" in result.stderr.lower() or "decode" in result.stderr.lower()
    print("  PASS")

    # =========================================================================
    # Test 3: Connection error (mocked)
    # =========================================================================
    print("\n--- Test 3: BMC connection error (mocked) ---")
    with patch("__main__.VmcObject") as MockVmc:
        mock_vmc_instance = MagicMock()
        mock_vmc_instance.execute.side_effect = RvmcConnectionError("Unable to ping BMC")
        mock_vmc_instance.__enter__ = MagicMock(return_value=mock_vmc_instance)
        mock_vmc_instance.__exit__ = MagicMock(return_value=False)
        MockVmc.return_value = mock_vmc_instance

        result = tool.execute(ToolRequest(correlation_id="t3", parameters=VALID_PARAMS))
        print(f"  success   : {result.success}")
        print(f"  stderr    : {result.stderr}")
        print(f"  error_type: {result.data.get('error_type')}")
        assert result.success is False
        assert result.data["error_type"] == "connection_failed"
        print("  PASS")

    # =========================================================================
    # Test 4: Auth error (mocked)
    # =========================================================================
    print("\n--- Test 4: BMC auth error (mocked) ---")
    with patch("__main__.VmcObject") as MockVmc:
        mock_vmc_instance = MagicMock()
        mock_vmc_instance.execute.side_effect = RvmcAuthError("Invalid credentials")
        mock_vmc_instance.__enter__ = MagicMock(return_value=mock_vmc_instance)
        mock_vmc_instance.__exit__ = MagicMock(return_value=False)
        MockVmc.return_value = mock_vmc_instance

        result = tool.execute(ToolRequest(correlation_id="t4", parameters=VALID_PARAMS))
        print(f"  success   : {result.success}")
        print(f"  stderr    : {result.stderr}")
        print(f"  error_type: {result.data.get('error_type')}")
        assert result.success is False
        assert result.data["error_type"] == "auth_failed"
        assert result.exit_code == 2
        print("  PASS")

    # =========================================================================
    # Test 5: Media error (mocked)
    # =========================================================================
    print("\n--- Test 5: Virtual media error (mocked) ---")
    with patch("__main__.VmcObject") as MockVmc:
        mock_vmc_instance = MagicMock()
        mock_vmc_instance.execute.side_effect = RvmcMediaError("No CD/DVD found")
        mock_vmc_instance.__enter__ = MagicMock(return_value=mock_vmc_instance)
        mock_vmc_instance.__exit__ = MagicMock(return_value=False)
        MockVmc.return_value = mock_vmc_instance

        result = tool.execute(ToolRequest(correlation_id="t5", parameters=VALID_PARAMS))
        print(f"  success   : {result.success}")
        print(f"  error_type: {result.data.get('error_type')}")
        assert result.success is False
        assert result.data["error_type"] == "media_error"
        print("  PASS")

    # =========================================================================
    # Test 6: Power error (mocked)
    # =========================================================================
    print("\n--- Test 6: Power control error (mocked) ---")
    with patch("__main__.VmcObject") as MockVmc:
        mock_vmc_instance = MagicMock()
        mock_vmc_instance.execute.side_effect = RvmcPowerError("Power off timed out")
        mock_vmc_instance.__enter__ = MagicMock(return_value=mock_vmc_instance)
        mock_vmc_instance.__exit__ = MagicMock(return_value=False)
        MockVmc.return_value = mock_vmc_instance

        result = tool.execute(ToolRequest(correlation_id="t6", parameters=VALID_PARAMS))
        print(f"  success   : {result.success}")
        print(f"  error_type: {result.data.get('error_type')}")
        assert result.success is False
        assert result.data["error_type"] == "power_error"
        print("  PASS")

    # =========================================================================
    # Test 7: Boot error (mocked)
    # =========================================================================
    print("\n--- Test 7: Boot override error (mocked) ---")
    with patch("__main__.VmcObject") as MockVmc:
        mock_vmc_instance = MagicMock()
        mock_vmc_instance.execute.side_effect = RvmcBootError("Unsupported boot mode")
        mock_vmc_instance.__enter__ = MagicMock(return_value=mock_vmc_instance)
        mock_vmc_instance.__exit__ = MagicMock(return_value=False)
        MockVmc.return_value = mock_vmc_instance

        result = tool.execute(ToolRequest(correlation_id="t7", parameters=VALID_PARAMS))
        print(f"  success   : {result.success}")
        print(f"  error_type: {result.data.get('error_type')}")
        assert result.success is False
        assert result.data["error_type"] == "boot_error"
        print("  PASS")

    # =========================================================================
    # Test 8: Unexpected error (mocked)
    # =========================================================================
    print("\n--- Test 8: Unexpected error (mocked) ---")
    with patch("__main__.VmcObject") as MockVmc:
        mock_vmc_instance = MagicMock()
        mock_vmc_instance.execute.side_effect = RuntimeError("cosmic ray")
        mock_vmc_instance.__enter__ = MagicMock(return_value=mock_vmc_instance)
        mock_vmc_instance.__exit__ = MagicMock(return_value=False)
        MockVmc.return_value = mock_vmc_instance

        result = tool.execute(ToolRequest(correlation_id="t8", parameters=VALID_PARAMS))
        print(f"  success   : {result.success}")
        print(f"  error_type: {result.data.get('error_type')}")
        assert result.success is False
        assert result.data["error_type"] == "unexpected"
        assert "RuntimeError" in result.stderr
        print("  PASS")

    # =========================================================================
    # Test 9: Successful install (mocked)
    # =========================================================================
    print("\n--- Test 9: Successful RVMC install (mocked) ---")
    with patch("__main__.VmcObject") as MockVmc:
        mock_vmc_instance = MagicMock()
        mock_vmc_instance.execute.return_value = None  # no exception = success
        mock_vmc_instance.__enter__ = MagicMock(return_value=mock_vmc_instance)
        mock_vmc_instance.__exit__ = MagicMock(return_value=False)
        MockVmc.return_value = mock_vmc_instance

        result = tool.execute(ToolRequest(correlation_id="t9", parameters=VALID_PARAMS))
        print(f"  success : {result.success}")
        print(f"  stdout  : {result.stdout}")
        print(f"  data    : {result.data}")
        assert result.success is True
        assert result.data["installed"] is True
        assert result.data["address"] == "10.0.0.1"
        assert result.data["image"] == "http://example.com/boot.iso"
        print("  PASS")

    # =========================================================================
    # Test 10: With optional target_name
    # =========================================================================
    print("\n--- Test 10: With target_name (mocked) ---")
    with patch("__main__.VmcObject") as MockVmc:
        mock_vmc_instance = MagicMock()
        mock_vmc_instance.execute.return_value = None
        mock_vmc_instance.__enter__ = MagicMock(return_value=mock_vmc_instance)
        mock_vmc_instance.__exit__ = MagicMock(return_value=False)
        MockVmc.return_value = mock_vmc_instance

        params_with_name = {**VALID_PARAMS, "target_name": "controller-0"}
        result = tool.execute(ToolRequest(correlation_id="t10", parameters=params_with_name))
        print(f"  success: {result.success}")
        print(f"  target : {result.data.get('target')}")
        assert result.success is True
        assert result.data["target"] == "controller-0"
        print("  PASS")

    # =========================================================================
    # Test 11: Tool definition
    # =========================================================================
    print("\n--- Test 11: Tool definition ---")
    defn = tool.definition
    print(f"  name       : {defn.name}")
    print(f"  description: {defn.description}")
    print(f"  in_schema  : {defn.input_schema}")
    assert defn.name == "wrcp_rvmc_install_base_tool"
    assert "bmc_address" in defn.input_schema
    assert "bmc_password" in defn.input_schema
    assert "image" in defn.input_schema
    print("  PASS")

    print("\u3555\n" + "=" * 60)
    print("  All WrcpRvmcInstallBaseTool tests complete. (11/11)")
    print("=" * 60)
