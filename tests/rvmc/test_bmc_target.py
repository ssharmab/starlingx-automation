# SPDX-License-Identifier: Apache-2.0
"""Tests for tools/rvmc/bmc_target.py — full branch coverage."""
import base64
from pathlib import Path

import pytest
from tools.rvmc.bmc_target import BmcTarget

# ---------------------------------------------------------------------------
# Load inventory once for the whole module.
# InventoryChecker validates schema, host format, and kubeconfig path.
# check_reachability / check_ssh_access are disabled so tests run offline.
# ---------------------------------------------------------------------------
_INVENTORY_PATH = (
    Path(__file__).parent.parent.parent / "inventory" / "inventory.yaml"
)


@pytest.fixture(scope="module")
def inventory():
    """Return a validated InventoryConfig from inventory/inventory.yaml."""
    from utils.inventory_checker import InventoryChecker
    return InventoryChecker(
        path=_INVENTORY_PATH,
        check_reachability=False,
        check_ssh_access=False,
    ).validate()


@pytest.fixture(scope="module")
def inventory_cfg(inventory):
    """
    Build the bmc_target config dict from inventory fields.
    Maps inventory.yaml keys → BmcTarget.from_config() expected keys.
    Password is base64-encoded as from_config() expects encoded input.
    """
    return {
        "bmc_address":  inventory.host,
        "bmc_username": inventory.login,
        "bmc_password": base64.b64encode(
            inventory.password.encode()
        ).decode(),
        "image":        inventory.image,
    }


class TestBmcTargetDirect:
    def test_fields_set(self, inventory):
        t = BmcTarget(
            address=inventory.host,
            username=inventory.login,
            password=inventory.password,
            image=inventory.image,
            target_name="test-target",
            debug=2,
        )
        assert t.address      == inventory.host
        assert t.username     == inventory.login
        assert t.password     == inventory.password
        assert t.image        == inventory.image
        assert t.target_name  == "test-target"
        assert t.debug        == 2

    def test_defaults(self, inventory):
        t = BmcTarget(
            address=inventory.host,
            username=inventory.login,
            password=inventory.password,
            image=inventory.image,
        )
        assert t.target_name is None
        assert t.debug == 0


class TestBmcTargetFromConfig:
    """Uses inventory/inventory.yaml as the credential source via InventoryChecker."""

    def test_happy_path(self, inventory, inventory_cfg):
        t = BmcTarget.from_config("tgt", inventory_cfg)
        assert t.address      == inventory.host
        assert t.username     == inventory.login
        assert t.password     == inventory.password
        assert t.image        == inventory.image
        assert t.target_name  == "tgt"
        assert t.debug        == 0

    def test_target_name_none(self, inventory_cfg):
        t = BmcTarget.from_config(None, inventory_cfg)
        assert t.target_name is None

    def test_debug_passed_through(self, inventory_cfg):
        t = BmcTarget.from_config("x", inventory_cfg, debug=3)
        assert t.debug == 3

    def test_strips_whitespace(self, inventory_cfg):
        cfg = dict(inventory_cfg)
        cfg["bmc_address"]  = "  " + inventory_cfg["bmc_address"] + "  "
        cfg["bmc_username"] = " " + inventory_cfg["bmc_username"] + " "
        cfg["image"]        = " http://x/b.iso "
        t = BmcTarget.from_config(None, cfg)
        assert t.address  == inventory_cfg["bmc_address"]
        assert t.username == inventory_cfg["bmc_username"]
        assert t.image    == "http://x/b.iso"

    def test_missing_password_raises(self, inventory_cfg):
        cfg = dict(inventory_cfg)
        del cfg["bmc_password"]
        with pytest.raises(ValueError, match="bmc_password"):
            BmcTarget.from_config(None, cfg)

    def test_invalid_base64_password_raises(self, inventory_cfg):
        cfg = dict(inventory_cfg)
        cfg["bmc_password"] = "not-valid-base64!!!"
        with pytest.raises(ValueError, match="decode"):
            BmcTarget.from_config(None, cfg)

    def test_missing_address_raises(self, inventory_cfg):
        cfg = dict(inventory_cfg)
        del cfg["bmc_address"]
        with pytest.raises(ValueError, match="bmc_address"):
            BmcTarget.from_config(None, cfg)

    def test_missing_image_raises(self, inventory_cfg):
        cfg = dict(inventory_cfg)
        del cfg["image"]
        with pytest.raises(ValueError, match="image"):
            BmcTarget.from_config(None, cfg)

    def test_missing_username_raises(self, inventory_cfg):
        cfg = dict(inventory_cfg)
        del cfg["bmc_username"]
        with pytest.raises(ValueError, match="bmc_username"):
            BmcTarget.from_config(None, cfg)
