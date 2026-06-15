# SPDX-License-Identifier: Apache-2.0
"""
Tests for tools/rvmc/rvmc.py — full branch coverage.

All Redfish, OS, and time calls are mocked so tests run without any
network access or real hardware.
"""
import json
from unittest.mock import MagicMock, call, patch

import pytest

from tools.rvmc.bmc_target import BmcTarget
from tools.rvmc.rvmc_errors import (
    RvmcAuthError,
    RvmcBootError,
    RvmcConnectionError,
    RvmcMediaError,
    RvmcPowerError,
    RvmcError,
)
from utils.tool_result import ResultStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resp(status: int, data: dict):
    r = MagicMock()
    r.status = status
    r.read = json.dumps(data)
    r.dict = data
    return r


def _make_vmc(address="192.168.1.10", debug=0):
    from tools.rvmc.rvmc import VmcObject
    t = BmcTarget(
        address=address,
        username="admin",
        password="secret",
        image="http://10.0.0.1/boot.iso",
        target_name="host1",
        debug=debug,
    )
    obj = VmcObject(t)
    obj.redfish_obj = MagicMock()
    obj.session = True
    return obj


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

class TestHeaders:
    def test_headers_are_dicts(self):
        from tools.rvmc import rvmc as m
        assert isinstance(m.GET_HEADERS, dict)
        assert isinstance(m.POST_HEADERS, dict)
        assert isinstance(m.PATCH_HEADERS, dict)

    def test_header_values(self):
        from tools.rvmc import rvmc as m
        for h in (m.GET_HEADERS, m.POST_HEADERS, m.PATCH_HEADERS):
            assert h["Content-Type"] == "application/json"
            assert h["Accept"] == "application/json"

    def test_hdr_constants_are_tuples(self):
        from tools.rvmc import rvmc as m
        assert m.HDR_CONTENT_TYPE == ("Content-Type", "application/json")
        assert m.HDR_ACCEPT == ("Accept", "application/json")


# ---------------------------------------------------------------------------
# _is_ipv6 / _supported_device helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_is_ipv6_true(self):
        from tools.rvmc.rvmc import _is_ipv6
        assert _is_ipv6("2001:db8::1") is True

    def test_is_ipv6_false(self):
        from tools.rvmc.rvmc import _is_ipv6
        assert _is_ipv6("192.168.1.1") is False

    def test_supported_device_cd(self):
        from tools.rvmc.rvmc import _supported_device
        assert _supported_device(["CD"]) is True

    def test_supported_device_dvd(self):
        from tools.rvmc.rvmc import _supported_device
        assert _supported_device(["DVD"]) is True

    def test_supported_device_false(self):
        from tools.rvmc.rvmc import _supported_device
        assert _supported_device(["USB"]) is False

    def test_supported_device_empty(self):
        from tools.rvmc.rvmc import _supported_device
        assert _supported_device([]) is False


# ---------------------------------------------------------------------------
# VmcObject.__init__
# ---------------------------------------------------------------------------

class TestVmcObjectInit:
    def test_ipv4_uri(self):
        vmc = _make_vmc("10.0.0.1")
        assert vmc.uri == "https://10.0.0.1"
        assert vmc.ipv6 is False

    def test_ipv6_uri(self):
        vmc = _make_vmc("2001:db8::1")
        assert vmc.uri == "https://[2001:db8::1]"
        assert vmc.ipv6 is True

    def test_debug_stored(self):
        vmc = _make_vmc(debug=3)
        assert vmc._debug == 3


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_enter_returns_self(self):
        vmc = _make_vmc()
        assert vmc.__enter__() is vmc

    def test_exit_calls_close(self):
        vmc = _make_vmc()
        vmc.close = MagicMock()
        vmc.__exit__(None, None, None)
        vmc.close.assert_called_once()

    def test_exit_returns_false(self):
        vmc = _make_vmc()
        assert vmc.__exit__(None, None, None) is False

    def test_close_when_session_open(self):
        vmc = _make_vmc()
        mock_redfish = vmc.redfish_obj   # hold ref before close() nulls it
        vmc.close()
        mock_redfish.logout.assert_called_once()
        assert vmc.redfish_obj is None
        assert vmc.session is False

    def test_close_when_no_session(self):
        vmc = _make_vmc()
        vmc.session = False
        vmc.close()
        vmc.redfish_obj.logout.assert_not_called()

    def test_close_logout_exception_handled(self):
        vmc = _make_vmc()
        vmc.redfish_obj.logout.side_effect = Exception("boom")
        vmc.close()   # must not raise
        assert vmc.session is False

    def test_context_manager_closes_on_exception(self):
        from tools.rvmc.rvmc import VmcObject
        t = BmcTarget(address="1.2.3.4", username="u", password="p",
                      image="http://x/b.iso")
        with pytest.raises(RvmcError):
            with VmcObject(t) as vmc:
                vmc.redfish_obj = MagicMock()
                vmc.session = True
                raise RvmcError("test error")


# ---------------------------------------------------------------------------
# make_request
# ---------------------------------------------------------------------------

class TestMakeRequest:
    def test_get_success_200(self):
        vmc = _make_vmc()
        vmc.redfish_obj.get.return_value = _resp(200, {"key": "val"})
        assert vmc.make_request(operation="GET", path="/redfish/v1") is True
        assert vmc.response_dict == {"key": "val"}

    def test_post_success_202(self):
        vmc = _make_vmc()
        vmc.redfish_obj.post.return_value = _resp(202, {"ok": True})
        assert vmc.make_request(operation="POST", path="/x", payload={}) is True

    def test_patch_success_200(self):
        vmc = _make_vmc()
        vmc.redfish_obj.patch.return_value = _resp(200, {"ok": True})
        assert vmc.make_request(operation="PATCH", path="/x", payload={}) is True

    def test_204_clears_response(self):
        vmc = _make_vmc()
        vmc.redfish_obj.post.return_value = _resp(204, {})
        vmc.redfish_obj.post.return_value.status = 204
        assert vmc.make_request(operation="POST", path="/x", payload={}) is True
        assert vmc.response == ""

    def test_unsupported_operation_raises(self):
        vmc = _make_vmc()
        with pytest.raises(RvmcError, match="Unsupported"):
            vmc.make_request(operation="DELETE", path="/x")

    def test_network_exception_raises(self):
        vmc = _make_vmc()
        vmc.redfish_obj.get.side_effect = Exception("network down")
        with pytest.raises(RvmcError, match="Request failed"):
            vmc.make_request(operation="GET", path="/x")

    def test_none_response_raises(self):
        vmc = _make_vmc()
        vmc.redfish_obj.get.return_value = None
        with pytest.raises(RvmcError, match="No response"):
            vmc.make_request(operation="GET", path="/x")

    @patch("tools.rvmc.rvmc.time.sleep")
    def test_transient_error_retries(self, mock_sleep):
        vmc = _make_vmc()
        bad = _resp(500, {})
        good = _resp(200, {"a": 1})
        vmc.redfish_obj.get.side_effect = [bad, good]
        result = vmc.make_request(operation="GET", path="/x", retry=0)
        assert result is True
        mock_sleep.assert_called()

    def test_max_retries_exceeded_raises(self):
        vmc = _make_vmc()
        vmc.redfish_obj.get.return_value = _resp(500, {})
        with pytest.raises(RvmcError, match="HTTP error"):
            vmc.make_request(operation="GET", path="/x", retry=-1)

    def test_uses_self_url_when_path_none(self):
        vmc = _make_vmc()
        vmc.redfish_obj.get.return_value = _resp(200, {"x": 1})
        vmc.make_request(operation="GET", path=None)
        vmc.redfish_obj.get.assert_called_once_with(
            vmc.url, headers=pytest.approx({"Content-Type": "application/json",
                                            "Accept": "application/json"}),
        )

    def test_debug4_logs_response(self):
        vmc = _make_vmc(debug=4)
        vmc.redfish_obj.get.return_value = _resp(200, {"x": 1})
        assert vmc.make_request(operation="GET", path="/x") is True


# ---------------------------------------------------------------------------
# _check_ok_status
# ---------------------------------------------------------------------------

class TestCheckOkStatus:
    def test_200_ok(self):
        vmc = _make_vmc()
        vmc.response = _resp(200, {})
        assert vmc._check_ok_status("/url", "GET", 1) is True

    def test_500_fail(self):
        vmc = _make_vmc()
        vmc.response = _resp(500, {})
        assert vmc._check_ok_status("/url", "GET", 1) is False

    def test_eject_400_accepted(self):
        vmc = _make_vmc()
        vmc.vm_eject_url = "/eject"
        vmc.response = _resp(400, {})
        assert vmc._check_ok_status("/eject", "POST", 1) is True

    def test_eject_403_accepted(self):
        vmc = _make_vmc()
        vmc.vm_eject_url = "/eject"
        vmc.response = _resp(403, {})
        assert vmc._check_ok_status("/eject", "POST", 1) is True

    def test_eject_404_accepted(self):
        vmc = _make_vmc()
        vmc.vm_eject_url = "/eject"
        vmc.response = _resp(404, {})
        assert vmc._check_ok_status("/eject", "POST", 1) is True

    def test_non_eject_url_400_fails(self):
        vmc = _make_vmc()
        vmc.vm_eject_url = "/eject"
        vmc.response = _resp(400, {})
        assert vmc._check_ok_status("/other", "POST", 1) is False

    def test_debug2_logs_ok(self):
        vmc = _make_vmc(debug=2)
        vmc.response = _resp(200, {})
        assert vmc._check_ok_status("/url", "GET", 1) is True


# ---------------------------------------------------------------------------
# _redfish_client_connect
# ---------------------------------------------------------------------------

class TestRedfishClientConnect:
    @patch("tools.rvmc.rvmc.time.sleep")
    @patch("tools.rvmc.rvmc.os.system", return_value=0)
    @patch("tools.rvmc.rvmc.redfish.redfish_client")
    def test_connect_success_ipv4(self, mock_client, mock_os, mock_sleep):
        vmc = _make_vmc()
        vmc.redfish_obj = None
        vmc.session = False
        mock_client.return_value = MagicMock()
        vmc._redfish_client_connect()
        assert vmc.redfish_obj is not None

    @patch("tools.rvmc.rvmc.time.sleep")
    @patch("tools.rvmc.rvmc.os.system", return_value=0)
    @patch("tools.rvmc.rvmc.redfish.redfish_client")
    def test_connect_success_ipv6(self, mock_client, mock_os, mock_sleep):
        vmc = _make_vmc("2001:db8::1")
        vmc.redfish_obj = None
        vmc.session = False
        mock_client.return_value = MagicMock()
        vmc._redfish_client_connect()
        assert vmc.redfish_obj is not None
        called_cmd = mock_os.call_args[0][0]
        assert "ping -6" in called_cmd

    @patch("tools.rvmc.rvmc.time.sleep")
    @patch("tools.rvmc.rvmc.os.system", return_value=0)
    @patch("tools.rvmc.rvmc.redfish.redfish_client")
    @patch("tools.rvmc.rvmc.sys.platform", "win32")
    def test_ping_uses_windows_flags(self, mock_client, mock_os, mock_sleep):
        vmc = _make_vmc()
        vmc.redfish_obj = None
        mock_client.return_value = MagicMock()
        vmc._redfish_client_connect()
        called_cmd = mock_os.call_args[0][0]
        assert "-n 1" in called_cmd
        assert "NUL" in called_cmd

    @patch("tools.rvmc.rvmc.time.sleep")
    @patch("tools.rvmc.rvmc.os.system", return_value=0)
    @patch("tools.rvmc.rvmc.redfish.redfish_client")
    @patch("tools.rvmc.rvmc.sys.platform", "linux")
    def test_ping_uses_linux_flags(self, mock_client, mock_os, mock_sleep):
        vmc = _make_vmc()
        vmc.redfish_obj = None
        mock_client.return_value = MagicMock()
        vmc._redfish_client_connect()
        called_cmd = mock_os.call_args[0][0]
        assert "-c 1" in called_cmd
        assert "/dev/null" in called_cmd

    @patch("tools.rvmc.rvmc.time.sleep")
    @patch("tools.rvmc.rvmc.os.system", return_value=1)
    def test_ping_failure_raises(self, mock_os, mock_sleep):
        vmc = _make_vmc()
        with pytest.raises(RvmcConnectionError, match="ping"):
            vmc._redfish_client_connect()

    @patch("tools.rvmc.rvmc.time.sleep")
    @patch("tools.rvmc.rvmc.os.system", return_value=0)
    @patch("tools.rvmc.rvmc.redfish.redfish_client", side_effect=Exception("refused"))
    def test_client_create_failure_raises(self, mock_client, mock_os, mock_sleep):
        vmc = _make_vmc()
        with pytest.raises(RvmcConnectionError, match="Cannot connect"):
            vmc._redfish_client_connect()

    @patch("tools.rvmc.rvmc.time.sleep")
    @patch("tools.rvmc.rvmc.os.system", return_value=0)
    @patch("tools.rvmc.rvmc.redfish.redfish_client", return_value=None)
    def test_client_returns_none_raises(self, mock_client, mock_os, mock_sleep):
        vmc = _make_vmc()
        with pytest.raises(RvmcConnectionError):
            vmc._redfish_client_connect()

    @patch("tools.rvmc.rvmc.time.sleep")
    @patch("tools.rvmc.rvmc.os.system", side_effect=[1, 1, 1, 1, 1, 1, 1, 1, 1, 1])
    def test_ping_retries_10_times(self, mock_os, mock_sleep):
        vmc = _make_vmc()
        with pytest.raises(RvmcConnectionError):
            vmc._redfish_client_connect()
        assert mock_os.call_count == 10


# ---------------------------------------------------------------------------
# _redfish_root_query
# ---------------------------------------------------------------------------

class TestRootQuery:
    def test_extracts_systems_url(self):
        vmc = _make_vmc()
        vmc.redfish_obj.get.return_value = _resp(200, {
            "Systems": {"@odata.id": "/redfish/v1/Systems/"}
        })
        vmc._redfish_root_query()
        assert vmc.systems_group_url == "/redfish/v1/Systems/"
        assert vmc.root_query_info is not None


# ---------------------------------------------------------------------------
# _redfish_create_session
# ---------------------------------------------------------------------------

class TestCreateSession:
    def test_login_success(self):
        vmc = _make_vmc()
        vmc.session = False
        vmc.redfish_obj.login.return_value = None
        vmc._redfish_create_session()
        assert vmc.session is True

    def test_invalid_credentials_raises(self):
        from redfish.rest.v1 import InvalidCredentialsError
        vmc = _make_vmc()
        vmc.redfish_obj.login.side_effect = InvalidCredentialsError
        with pytest.raises(RvmcAuthError, match="credentials"):
            vmc._redfish_create_session()

    @patch("tools.rvmc.rvmc.time.sleep")
    def test_retries_then_raises(self, mock_sleep):
        vmc = _make_vmc()
        vmc.redfish_obj.login.side_effect = Exception("timeout")
        with pytest.raises(RvmcAuthError, match="attempts"):
            vmc._redfish_create_session()


# ---------------------------------------------------------------------------
# _redfish_get_managers
# ---------------------------------------------------------------------------

class TestGetManagers:
    def test_success(self):
        vmc = _make_vmc()
        members = [{"@odata.id": "/redfish/v1/Managers/1/"}]
        vmc.redfish_obj.get.side_effect = [
            _resp(200, {
                "Systems":  {"@odata.id": "/redfish/v1/Systems/"},
                "Managers": {"@odata.id": "/redfish/v1/Managers/"},
            }),
            _resp(200, {"Members": members}),
        ]
        vmc._redfish_root_query()
        vmc._redfish_get_managers()
        assert vmc.managers_group_url == "/redfish/v1/Managers/"
        assert vmc.manager_members_list == members

    def test_no_managers_link_raises(self):
        vmc = _make_vmc()
        vmc.redfish_obj.get.return_value = _resp(200, {
            "Systems": {"@odata.id": "/redfish/v1/Systems/"}
            # no Managers key
        })
        vmc._redfish_root_query()
        with pytest.raises(RvmcError, match="Managers link"):
            vmc._redfish_get_managers()


# ---------------------------------------------------------------------------
# _redfish_get_systems_members
# ---------------------------------------------------------------------------

class TestGetSystemsMembers:
    def test_success(self):
        vmc = _make_vmc()
        members = [{"@odata.id": "/redfish/v1/Systems/1/"}]
        vmc.systems_group_url = "/redfish/v1/Systems/"
        vmc.redfish_obj.get.return_value = _resp(200, {"Members": members})
        vmc._redfish_get_systems_members()
        assert vmc.systems_members == 1

    def test_empty_members_raises(self):
        vmc = _make_vmc()
        vmc.systems_group_url = "/redfish/v1/Systems/"
        vmc.redfish_obj.get.return_value = _resp(200, {"Members": []})
        with pytest.raises(RvmcError, match="No Systems Members"):
            vmc._redfish_get_systems_members()

    def test_none_members_raises(self):
        vmc = _make_vmc()
        vmc.systems_group_url = "/redfish/v1/Systems/"
        vmc.redfish_obj.get.return_value = _resp(200, {})
        with pytest.raises(RvmcError, match="No Systems Members"):
            vmc._redfish_get_systems_members()


# ---------------------------------------------------------------------------
# _redfish_powerctl_host
# ---------------------------------------------------------------------------

class TestPowerctl:
    def _reset_dict(self, state="Off"):
        return {
            "target": "/redfish/v1/Systems/1/Actions/ComputerSystem.Reset/",
            "ResetType@Redfish.AllowableValues": ["ForceOff", "GracefulShutdown", "On"],
        }

    def test_already_in_state_returns(self):
        vmc = _make_vmc()
        vmc.power_state = "Off"
        vmc._redfish_powerctl_host("Off")   # should return immediately

    @patch("tools.rvmc.rvmc.time.sleep")
    @patch("tools.rvmc.rvmc.time.time", side_effect=[0, 5, 900])
    def test_power_off_success(self, mock_time, mock_sleep):
        vmc = _make_vmc()
        vmc.systems_members_list = [{"@odata.id": "/redfish/v1/Systems/1/"}]
        vmc.systems_members = 1
        vmc.redfish_obj.get.return_value = _resp(200, {
            "PowerState": "On",
            "Actions": {"#ComputerSystem.Reset": self._reset_dict()},
        })
        vmc.redfish_obj.post.return_value = _resp(200, {})
        # After POST, polls: first still On, then Off
        vmc.redfish_obj.get.side_effect = [
            _resp(200, {"PowerState": "On",
                        "Actions": {"#ComputerSystem.Reset": self._reset_dict()}}),
            _resp(200, {"PowerState": "Off"}),
        ]
        with patch("tools.rvmc.rvmc.time.time", side_effect=[0, 5, 5, 5]):
            with patch("tools.rvmc.rvmc.time.sleep"):
                vmc._redfish_powerctl_host("Off")
        assert vmc.power_state == "Off"

    def test_no_reset_dict_raises(self):
        vmc = _make_vmc()
        vmc.systems_members_list = [{"@odata.id": "/redfish/v1/Systems/1/"}]
        vmc.redfish_obj.get.return_value = _resp(200, {
            "PowerState": "Off",
            "Actions": {}   # Actions present but no ComputerSystem.Reset key
        })
        with pytest.raises(RvmcPowerError, match="Reset Action"):
            vmc._redfish_powerctl_host("On")

    def test_no_reset_command_url_raises(self):
        vmc = _make_vmc()
        vmc.systems_members_list = [{"@odata.id": "/redfish/v1/Systems/1/"}]
        vmc.redfish_obj.get.return_value = _resp(200, {
            "PowerState": "Off",
            "Actions": {"#ComputerSystem.Reset": {
                "ResetType@Redfish.AllowableValues": ["On"]
                # no 'target'
            }},
        })
        with pytest.raises(RvmcPowerError, match="Reset command URL"):
            vmc._redfish_powerctl_host("On")

    def test_no_allowable_values_raises(self):
        vmc = _make_vmc()
        vmc.systems_members_list = [{"@odata.id": "/redfish/v1/Systems/1/"}]
        vmc.redfish_obj.get.return_value = _resp(200, {
            "PowerState": "Off",
            "Actions": {"#ComputerSystem.Reset": {"target": "/reset"}},
        })
        with pytest.raises(RvmcPowerError, match="allowable"):
            vmc._redfish_powerctl_host("On")

    def test_no_acceptable_command_raises(self):
        vmc = _make_vmc()
        vmc.systems_members_list = [{"@odata.id": "/redfish/v1/Systems/1/"}]
        vmc.redfish_obj.get.return_value = _resp(200, {
            "PowerState": "Off",
            "Actions": {"#ComputerSystem.Reset": {
                "target": "/reset",
                "ResetType@Redfish.AllowableValues": ["NMI"],
            }},
        })
        with pytest.raises(RvmcPowerError, match="No acceptable"):
            vmc._redfish_powerctl_host("On")

    @patch("tools.rvmc.rvmc.time.sleep")
    def test_power_timeout_raises(self, mock_sleep):
        vmc = _make_vmc()
        vmc.systems_members_list = [{"@odata.id": "/redfish/v1/Systems/1/"}]
        vmc.redfish_obj.get.return_value = _resp(200, {
            "PowerState": "On",
            "Actions": {"#ComputerSystem.Reset": {
                "target": "/reset",
                "ResetType@Redfish.AllowableValues": ["ForceOff"],
            }},
        })
        vmc.redfish_obj.post.return_value = _resp(200, {})
        with patch.dict("os.environ", {"RVMC_POWER_ACTION_TIMEOUT": "0"}):
            with pytest.raises(RvmcPowerError, match="did not reach"):
                vmc._redfish_powerctl_host("Off")

    def test_graceful_restart_command(self):
        vmc = _make_vmc()
        vmc.systems_members_list = [{"@odata.id": "/redfish/v1/Systems/1/"}]
        vmc.redfish_obj.get.return_value = _resp(200, {
            "PowerState": "On",
            "Actions": {"#ComputerSystem.Reset": {
                "target": "/reset",
                "ResetType@Redfish.AllowableValues": ["GracefulRestart"],
            }},
        })
        vmc.redfish_obj.post.return_value = _resp(200, {})
        # state="Restart" — not in [POWER_OFF, POWER_ON] so no poll
        vmc._redfish_powerctl_host("Restart")


# ---------------------------------------------------------------------------
# _redfish_get_vm_url
# ---------------------------------------------------------------------------

class TestGetVmUrl:
    def test_no_members_raises(self):
        vmc = _make_vmc()
        vmc.manager_members_list = []
        with pytest.raises(RvmcMediaError, match="No Manager"):
            vmc._redfish_get_vm_url()

    def test_none_member_skipped(self):
        vmc = _make_vmc()
        vmc.manager_members_list = [None, {"@odata.id": "/mgr/1/"}]
        vmc.redfish_obj.get.side_effect = [
            _resp(200, {"VirtualMedia": {"@odata.id": "/mgr/1/vm/"}}),
            _resp(200, {"Members": [{"@odata.id": "/mgr/1/vm/1/"}]}),
            _resp(200, {"MediaTypes": ["CD"]}),
        ]
        vmc._redfish_get_vm_url()
        assert vmc.vm_url == "/mgr/1/vm/1/"

    def test_no_virtual_media_key_skips_member(self):
        vmc = _make_vmc()
        vmc.manager_members_list = [{"@odata.id": "/mgr/1/"}]
        vmc.redfish_obj.get.return_value = _resp(200, {})
        with pytest.raises(RvmcMediaError, match="No CD/DVD"):
            vmc._redfish_get_vm_url()

    def test_no_group_url_raises(self):
        vmc = _make_vmc()
        vmc.manager_members_list = [{"@odata.id": "/mgr/1/"}]
        vmc.redfish_obj.get.return_value = _resp(200, {"VirtualMedia": {}})
        with pytest.raises(RvmcMediaError, match="group URL"):
            vmc._redfish_get_vm_url()

    def test_empty_vm_members_raises(self):
        vmc = _make_vmc()
        vmc.manager_members_list = [{"@odata.id": "/mgr/1/"}]
        vmc.redfish_obj.get.side_effect = [
            _resp(200, {"VirtualMedia": {"@odata.id": "/mgr/1/vm/"}}),
            _resp(200, {"Members": []}),
        ]
        with pytest.raises(RvmcMediaError, match="No Virtual Media members"):
            vmc._redfish_get_vm_url()

    def test_unsupported_media_type_skipped(self):
        vmc = _make_vmc()
        vmc.manager_members_list = [{"@odata.id": "/mgr/1/"}]
        vmc.redfish_obj.get.side_effect = [
            _resp(200, {"VirtualMedia": {"@odata.id": "/mgr/1/vm/"}}),
            _resp(200, {"Members": [{"@odata.id": "/mgr/1/vm/1/"}]}),
            _resp(200, {"MediaTypes": ["USB"]}),
        ]
        with pytest.raises(RvmcMediaError, match="No CD/DVD"):
            vmc._redfish_get_vm_url()

    def test_none_vm_member_url_skipped(self):
        vmc = _make_vmc()
        vmc.manager_members_list = [{"@odata.id": "/mgr/1/"}]
        vmc.redfish_obj.get.side_effect = [
            _resp(200, {"VirtualMedia": {"@odata.id": "/mgr/1/vm/"}}),
            _resp(200, {"Members": [None, {"@odata.id": "/mgr/1/vm/2/"}]}),
            _resp(200, {"MediaTypes": ["DVD"]}),
        ]
        vmc._redfish_get_vm_url()
        assert vmc.vm_url == "/mgr/1/vm/2/"


# ---------------------------------------------------------------------------
# _redfish_load_vm_actions
# ---------------------------------------------------------------------------

class TestLoadVmActions:
    def test_none_vm_url_raises(self):
        vmc = _make_vmc()
        vmc.vm_url = None
        with pytest.raises(RvmcMediaError, match="VM URL is None"):
            vmc._redfish_load_vm_actions()

    def test_loads_actions(self):
        vmc = _make_vmc()
        vmc.vm_url = "/vm/1/"
        actions = {"#VirtualMedia.EjectMedia": {"target": "/eject"}}
        vmc.response_dict = {
            "@odata.type": "#VirtualMedia.v1_2_0.VirtualMedia",
            "Actions": actions,
        }
        vmc._redfish_load_vm_actions()
        assert vmc.vm_label   == "#VirtualMedia"
        assert vmc.vm_version == "v1_2_0"
        assert vmc.vm_actions == actions

    def test_no_odata_type(self):
        vmc = _make_vmc()
        vmc.vm_url = "/vm/1/"
        vmc.response_dict = {}
        vmc._redfish_load_vm_actions()  # should not raise
        assert vmc.vm_label is None

    def test_single_part_odata_type(self):
        vmc = _make_vmc()
        vmc.vm_url = "/vm/1/"
        vmc.response_dict = {"@odata.type": "VirtualMedia"}
        vmc._redfish_load_vm_actions()
        assert vmc.vm_label   == "VirtualMedia"
        assert vmc.vm_version is None


# ---------------------------------------------------------------------------
# _redfish_eject_image
# ---------------------------------------------------------------------------

class TestEjectImage:
    def test_already_not_inserted(self):
        vmc = _make_vmc()
        vmc.vm_url = "/vm/1/"
        vmc.redfish_obj.get.return_value = _resp(200, {"Inserted": False})
        vmc._redfish_eject_image()   # returns immediately

    @patch("tools.rvmc.rvmc.time.sleep")
    def test_eject_success(self, mock_sleep):
        vmc = _make_vmc()
        vmc.vm_url = "/vm/1/"
        vmc.vm_actions = {"#VirtualMedia.EjectMedia": {"target": "/eject"}}
        vmc.redfish_obj.get.side_effect = [
            _resp(200, {"Inserted": True, "Image": "http://x/b.iso"}),   # initial check
            _resp(200, {"Inserted": False}),                              # poll: ejected
        ]
        vmc.redfish_obj.post.return_value = _resp(200, {})
        vmc._redfish_eject_image()

    def test_no_eject_action_raises(self):
        vmc = _make_vmc()
        vmc.vm_url = "/vm/1/"
        vmc.vm_actions = {}
        vmc.redfish_obj.get.return_value = _resp(200, {"Inserted": True})
        with pytest.raises(RvmcMediaError, match="Eject action not found"):
            vmc._redfish_eject_image()

    def test_no_eject_target_url_raises(self):
        vmc = _make_vmc()
        vmc.vm_url = "/vm/1/"
        # key is present but target is missing — must reach target check
        vmc.vm_actions = {"#VirtualMedia.EjectMedia": {"not-target": "/x"}}
        vmc.redfish_obj.get.return_value = _resp(200, {"Inserted": True})
        with pytest.raises(RvmcMediaError, match="Eject target URL"):
            vmc._redfish_eject_image()

    @patch("tools.rvmc.rvmc.time.sleep")
    def test_eject_timeout_raises(self, mock_sleep):
        from tools.rvmc import rvmc as m
        original = m.MAX_POLL_COUNT
        m.MAX_POLL_COUNT = 1
        try:
            vmc = _make_vmc()
            vmc.vm_url = "/vm/1/"
            vmc.vm_actions = {"#VirtualMedia.EjectMedia": {"target": "/eject"}}
            # Always return Inserted=True with no Image (polls inner loop, then outer)
            vmc.redfish_obj.get.return_value = _resp(200, {"Inserted": True, "Image": None})
            vmc.redfish_obj.post.return_value = _resp(200, {})
            with pytest.raises(RvmcMediaError, match="timed out"):
                vmc._redfish_eject_image()
        finally:
            m.MAX_POLL_COUNT = original


# ---------------------------------------------------------------------------
# _redfish_insert_image
# ---------------------------------------------------------------------------

class TestInsertImage:
    def test_no_insert_url_raises(self):
        vmc = _make_vmc()
        vmc.vm_actions = {}
        with pytest.raises(RvmcMediaError, match="InsertMedia"):
            vmc._redfish_insert_image()

    def test_no_insert_act_raises(self):
        vmc = _make_vmc()
        vmc.vm_actions = {"#VirtualMedia.InsertMedia": None}
        with pytest.raises(RvmcMediaError):
            vmc._redfish_insert_image()

    @patch("tools.rvmc.rvmc.time.sleep")
    def test_insert_success(self, mock_sleep):
        vmc = _make_vmc()
        vmc.vm_url = "/vm/1/"
        vmc.vm_actions = {"#VirtualMedia.InsertMedia": {"target": "/insert"}}
        vmc.redfish_obj.post.return_value = _resp(200, {})
        vmc.redfish_obj.get.return_value = _resp(200, {
            "Image": "http://10.0.0.1/boot.iso"
        })
        vmc._redfish_insert_image()

    @patch("tools.rvmc.rvmc.time.sleep")
    def test_insert_timeout_raises(self, mock_sleep):
        from tools.rvmc import rvmc as m
        original = m.MAX_POLL_COUNT
        m.MAX_POLL_COUNT = 1
        try:
            vmc = _make_vmc()
            vmc.vm_url = "/vm/1/"
            vmc.vm_actions = {"#VirtualMedia.InsertMedia": {"target": "/insert"}}
            vmc.redfish_obj.post.return_value = _resp(200, {})
            vmc.redfish_obj.get.return_value = _resp(200, {"Image": "wrong"})
            with pytest.raises(RvmcMediaError, match="timed out"):
                vmc._redfish_insert_image()
        finally:
            m.MAX_POLL_COUNT = original


# ---------------------------------------------------------------------------
# _redfish_set_boot_override
# ---------------------------------------------------------------------------

class TestSetBootOverride:
    def _boot_resp(self, mode_list=None, enabled="Once", device="UsbCd", bmode="UEFI"):
        data = {
            "Boot": {
                "BootSourceOverrideEnabled": enabled,
                "BootSourceOverrideTarget": device,
                "BootSourceOverrideMode": bmode,
            }
        }
        if mode_list is not None:
            data["Boot"]["BootSourceOverrideMode@Redfish.AllowableValues"] = mode_list
        return _resp(200, data)

    def test_no_boot_dict_raises(self):
        vmc = _make_vmc()
        vmc.systems_members_list = [{"@odata.id": "/sys/1/"}]
        vmc.redfish_obj.get.return_value = _resp(200, {})
        with pytest.raises(RvmcBootError, match="Boot control"):
            vmc._redfish_set_boot_override()

    def test_uefi_mode(self):
        vmc = _make_vmc()
        vmc.vm_media_types = ["CD"]
        vmc.systems_members_list = [{"@odata.id": "/sys/1/"}]
        vmc.redfish_obj.get.side_effect = [
            self._boot_resp(["UEFI"]),   # initial GET
            self._boot_resp(["UEFI"]),   # verify GET
        ]
        vmc.redfish_obj.patch.return_value = _resp(200, {})
        vmc._redfish_set_boot_override()

    def test_legacy_mode(self):
        vmc = _make_vmc()
        vmc.vm_media_types = ["CD"]
        vmc.systems_members_list = [{"@odata.id": "/sys/1/"}]
        vmc.redfish_obj.get.side_effect = [
            self._boot_resp(["Legacy"], bmode="Legacy"),
            self._boot_resp(["Legacy"], bmode="Legacy"),
        ]
        vmc.redfish_obj.patch.return_value = _resp(200, {})
        vmc._redfish_set_boot_override()

    def test_no_mode_list_uses_default(self):
        vmc = _make_vmc()
        vmc.vm_media_types = ["DVD"]
        vmc.systems_members_list = [{"@odata.id": "/sys/1/"}]
        vmc.redfish_obj.get.side_effect = [
            self._boot_resp(None),
            self._boot_resp(None),
        ]
        vmc.redfish_obj.patch.return_value = _resp(200, {})
        vmc._redfish_set_boot_override()

    def test_unsupported_mode_raises(self):
        vmc = _make_vmc()
        vmc.vm_media_types = ["CD"]
        vmc.systems_members_list = [{"@odata.id": "/sys/1/"}]
        vmc.redfish_obj.get.return_value = self._boot_resp(["Unknown"])
        with pytest.raises(RvmcBootError, match="Unsupported"):
            vmc._redfish_set_boot_override()

    def test_verify_fails_raises(self):
        vmc = _make_vmc()
        vmc.vm_media_types = ["CD"]
        vmc.systems_members_list = [{"@odata.id": "/sys/1/"}]
        vmc.redfish_obj.get.side_effect = [
            self._boot_resp(["UEFI"]),
            self._boot_resp(["UEFI"], enabled="Never"),  # verify fails
        ]
        vmc.redfish_obj.patch.return_value = _resp(200, {})
        with pytest.raises(RvmcBootError, match="verification failed"):
            vmc._redfish_set_boot_override()

    def test_none_member_skipped(self):
        vmc = _make_vmc()
        vmc.vm_media_types = ["CD"]
        vmc.systems_members_list = [None, {"@odata.id": "/sys/1/"}]
        vmc.redfish_obj.get.side_effect = [
            self._boot_resp(["UEFI"]),
            self._boot_resp(["UEFI"]),
        ]
        vmc.redfish_obj.patch.return_value = _resp(200, {})
        vmc._redfish_set_boot_override()


# ---------------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------------

class TestExecute:
    def test_execute_calls_all_stages(self):
        vmc = _make_vmc()
        stages = [
            "_redfish_client_connect",
            "_redfish_root_query",
            "_redfish_create_session",
            "_redfish_get_managers",
            "_redfish_get_systems_members",
            "_redfish_get_vm_url",
            "_redfish_load_vm_actions",
            "_redfish_eject_image",
            "_redfish_poweroff_host",
            "_redfish_insert_image",
            "_redfish_set_boot_override",
            "_redfish_poweron_host",
        ]
        for stage in stages:
            setattr(vmc, stage, MagicMock())
        vmc.execute()
        for stage in stages:
            getattr(vmc, stage).assert_called_once()


# ---------------------------------------------------------------------------
# run_rvmc
# ---------------------------------------------------------------------------

class TestRunRvmc:
    def _target(self):
        return BmcTarget(
            address="1.2.3.4", username="u", password="p",
            image="http://x/b.iso", target_name="t1",
        )

    @patch("tools.rvmc.rvmc.VmcObject")
    def test_success(self, MockVmc):
        from tools.rvmc.rvmc import run_rvmc
        inst = MockVmc.return_value.__enter__.return_value
        inst.execute.return_value = None
        result = run_rvmc(self._target())
        assert result.success is True
        assert result.status == ResultStatus.SUCCESS

    @patch("tools.rvmc.rvmc.VmcObject")
    def test_auth_error(self, MockVmc):
        from tools.rvmc.rvmc import run_rvmc
        MockVmc.return_value.__enter__.side_effect = RvmcAuthError("bad creds")
        result = run_rvmc(self._target())
        assert result.status == ResultStatus.AUTH_ERROR

    @patch("tools.rvmc.rvmc.VmcObject")
    def test_connection_error(self, MockVmc):
        from tools.rvmc.rvmc import run_rvmc
        MockVmc.return_value.__enter__.side_effect = RvmcConnectionError("unreachable")
        result = run_rvmc(self._target())
        assert result.status == ResultStatus.NOT_CONNECTED

    @patch("tools.rvmc.rvmc.VmcObject")
    def test_rvmc_error(self, MockVmc):
        from tools.rvmc.rvmc import run_rvmc
        MockVmc.return_value.__enter__.side_effect = RvmcError("generic")
        result = run_rvmc(self._target())
        assert result.status == ResultStatus.FAILURE

    @patch("tools.rvmc.rvmc.VmcObject")
    def test_unexpected_exception(self, MockVmc):
        from tools.rvmc.rvmc import run_rvmc
        MockVmc.return_value.__enter__.side_effect = RuntimeError("surprise")
        result = run_rvmc(self._target())
        assert result.status == ResultStatus.FAILURE
        assert "Unexpected" in result.stderr

    @patch("tools.rvmc.rvmc.VmcObject")
    def test_no_target_name_uses_address(self, MockVmc):
        from tools.rvmc.rvmc import run_rvmc
        t = BmcTarget(address="1.2.3.4", username="u", password="p",
                      image="http://x/b.iso")
        inst = MockVmc.return_value.__enter__.return_value
        inst.execute.return_value = None
        result = run_rvmc(t)
        assert "1.2.3.4" in result.stdout
