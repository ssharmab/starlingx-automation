# SPDX-License-Identifier: Apache-2.0
"""
conftest.py
-----------
Shared pytest fixtures for the full test suite.
"""
import base64
import sys
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest

# Make the project root importable from tests/
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# BmcTarget fixture helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_cfg():
    """Raw config dict as loaded from rvmc.yaml."""
    return {
        "bmc_address":  "192.168.1.10",
        "bmc_username": "admin",
        "bmc_password": base64.b64encode(b"secret").decode(),
        "image":        "http://10.0.0.1:8080/boot.iso",
    }


@pytest.fixture
def ipv6_cfg():
    return {
        "bmc_address":  "2001:db8::1",
        "bmc_username": "admin",
        "bmc_password": base64.b64encode(b"secret").decode(),
        "image":        "http://[2001:db8::2]:8080/boot.iso",
    }


@pytest.fixture
def bmc_target(valid_cfg):
    from tools.rvmc.bmc_target import BmcTarget
    return BmcTarget.from_config("test-target", valid_cfg)


@pytest.fixture
def ipv6_target(ipv6_cfg):
    from tools.rvmc.bmc_target import BmcTarget
    return BmcTarget.from_config("ipv6-target", ipv6_cfg)


# ---------------------------------------------------------------------------
# Mock Redfish response helper
# ---------------------------------------------------------------------------

def make_response(status: int, data: dict):
    """Build a mock Redfish response with .status and .read attributes."""
    import json
    resp = MagicMock()
    resp.status = status
    resp.read = json.dumps(data)
    resp.dict = data
    return resp


@pytest.fixture
def mock_response():
    return make_response


# ---------------------------------------------------------------------------
# VmcObject with mocked redfish_obj
# ---------------------------------------------------------------------------

@pytest.fixture
def vmc(bmc_target):
    from tools.rvmc.rvmc import VmcObject
    obj = VmcObject(bmc_target)
    obj.redfish_obj = MagicMock()
    obj.session = True
    return obj


@pytest.fixture
def vmc_ipv6(ipv6_target):
    from tools.rvmc.rvmc import VmcObject
    obj = VmcObject(ipv6_target)
    obj.redfish_obj = MagicMock()
    obj.session = True
    return obj
