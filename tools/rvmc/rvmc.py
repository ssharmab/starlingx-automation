#!/usr/bin/python3
# SPDX-License-Identifier: Apache-2.0
"""
rvmc.py
-------
Redfish Virtual Media Controller — agent-compatible edition.

Performs a BMC-driven OS install by injecting an ISO image via the Redfish
protocol and power-cycling the host to boot from it.

Steps executed by VmcObject.execute():
    1. Client Connect  ... establish Redfish client connection to the BMC
    2. Root Query      ... learn Redfish services offered by the BMC
    3. Create Session  ... open an authenticated Redfish session
    4. Get Managers    ... locate the VirtualMedia service URL
    5. Get Systems     ... discover Systems members for power/boot control
    6. Find CD/DVD     ... locate the virtual media CD/DVD device URL
    7. Load VM Actions ... extract eject/insert action URLs
    8. Eject Image     ... eject any currently mounted ISO
    9. Power Off Host  ... ensure host is powered off before insertion
   10. Insert Image    ... mount the target ISO and verify
   11. Boot Override   ... set one-time boot from CD/DVD
   12. Power On Host   ... boot the host from the injected ISO

Agent interface:
    result = run_rvmc(target)          # returns ToolResult, never sys.exit
    with VmcObject(target) as vmc:     # context manager, session always closed
        vmc.execute()

Standalone CLI (legacy):
    > python rvmc.py [--target t1,t2] [--debug 0-4]
    Config read from rvmc.yaml only in __main__ block.
"""

import datetime
import json
import os
import socket
import sys
import time

import redfish
from redfish.rest.v1 import InvalidCredentialsError
from common.tool_result import ToolResult
from common.tool_request import ToolRequest
from tools.base import BaseTool
from tools.rvmc.bmc_target import BmcTarget
from tools.rvmc.rvmc_errors import (
    RvmcError,
    RvmcAuthError,
    RvmcBootError,
    RvmcConnectionError,
    RvmcMediaError,
    RvmcPowerError,
)

FEATURE_NAME = 'Redfish Virtual Media Controller'
VERSION_MAJOR = 2
VERSION_MINOR = 3

POWER_ON = 'On'
POWER_OFF = 'Off'

REDFISH_ROOT_PATH = '/redfish/v1'
PRIMARY_CONFIG_LABEL = 'virtual_media_iso'
SUPPORTED_VIRTUAL_MEDIA_DEVICES = ['CD', 'DVD']

# Header constants as (key, value) tuples — unpacked into dicts per operation
HDR_CONTENT_TYPE = ("Content-Type", "application/json")
HDR_ACCEPT       = ("Accept",       "application/json")

GET_HEADERS   = dict([HDR_CONTENT_TYPE, HDR_ACCEPT])
POST_HEADERS  = dict([HDR_CONTENT_TYPE, HDR_ACCEPT])
PATCH_HEADERS = dict([HDR_CONTENT_TYPE, HDR_ACCEPT])

POST  = 'POST'
GET   = 'GET'
PATCH = 'PATCH'

MAX_POLL_COUNT                  = 200
RETRY_DELAY_SECS                = 10
DELAY_2_SECS                    = 2
MAX_CONNECTION_ATTEMPTS         = 3
CONNECTION_RETRY_INTERVAL       = 15
MAX_SESSION_CREATION_ATTEMPTS   = 3
SESSION_CREATION_RETRY_INTERVAL = 15
MAX_HTTP_TRANSIENT_ERROR_RETRIES = 5
HTTP_REQUEST_RETRY_INTERVAL     = 10


###############################################################################
# Logging helpers  (instance-level debug carried via closure over self.debug)
###############################################################################

def _t():
    return datetime.datetime.now().replace(microsecond=0)


def _ilog(msg):  sys.stdout.write("\n%s Info  : %s" % (_t(), msg))
def _wlog(msg):  sys.stdout.write("\n%s Warn  : %s" % (_t(), msg))
def _elog(msg):  sys.stdout.write("\n%s Error : %s" % (_t(), msg))
def _alog(msg):  sys.stdout.write("\n%s Action: %s" % (_t(), msg))
def _slog(msg):  sys.stdout.write("\n%s Stage : %s" % (_t(), msg))


def _dlog(msg, level, debug):
    if debug and level <= debug:
        sys.stdout.write("\n%s Debug%d: %s" % (_t(), level, msg))


###############################################################################
# Helpers
###############################################################################

def _is_ipv6(address: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET6, address)
        return True
    except socket.error:
        return False


def _supported_device(devices: list) -> bool:
    return any(d in SUPPORTED_VIRTUAL_MEDIA_DEVICES for d in devices)


###############################################################################
# VmcObject
###############################################################################

class VmcObject(BaseTool):
    """
    Virtual Media Controller — one instance per BMC target.

    Implements the full 12-step Redfish ISO injection pipeline and the
    context manager protocol so the Redfish session is always closed
    regardless of success or failure.

    Usage:
        with VmcObject(target) as vmc:
            vmc.execute()
    """

    def __init__(self, target: BmcTarget):
        self._debug = target.debug
        self.target_name = target.target_name
        self.ip = target.address.strip()
        self.un = target.username.strip()
        self.pw = target.password
        self.img = target.image.strip()

        # Wrap IPv6 addresses in brackets for URL construction only
        if _is_ipv6(self.ip):
            self.ipv6 = True
            self.uri = "https://[%s]" % self.ip
        else:
            self.ipv6 = False
            self.uri = "https://%s" % self.ip

        self.url = REDFISH_ROOT_PATH

        # Redfish session state
        self.redfish_obj = None
        self.session = False

        # Response state
        self.response      = None
        self.response_json = None
        self.response_dict = None

        # Discovered resource URLs / data
        self.root_query_info      = None
        self.managers_group_url   = None
        self.manager_members_list = []
        self.vm_url               = None
        self.vm_eject_url         = None
        self.vm_group_url         = None
        self.vm_group             = None
        self.vm_label             = None
        self.vm_version           = None
        self.vm_actions           = {}
        self.vm_members_array     = []
        self.vm_media_types       = []
        self.systems_group_url    = None
        self.systems_member_url   = None
        self.systems_members_list = []
        self.systems_members      = 0
        self.power_state          = None
        self.boot_control_dict    = {}
        self.reset_command_url    = None
        self.reset_action_dict    = {}

        self._ilog("%s v%d.%d" % (FEATURE_NAME, VERSION_MAJOR, VERSION_MINOR))
        self._dlog1("Target : %s" % self.target_name)
        self._dlog1("BMC IP : %s" % self.ip)

    # ------------------------------------------------------------------
    # Context manager — guarantees session close on exit
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False  # never suppress exceptions

    def close(self):
        """Close the Redfish session if one is open."""
        if self.redfish_obj is not None and self.session:
            try:
                self.redfish_obj.logout()
                self._dlog1("Session : Closed")
            except Exception as ex:
                _elog("Session close failed: %s" % ex)
            finally:
                self.redfish_obj = None
                self.session = False

    # ------------------------------------------------------------------
    # Instance-level log helpers (carry self._debug)
    # ------------------------------------------------------------------

    def _ilog(self, msg):  _ilog(msg)
    def _wlog(self, msg):  _wlog(msg)
    def _elog(self, msg):  _elog(msg)
    def _alog(self, msg):  _alog(msg)
    def _slog(self, msg):  _slog(msg)
    def _dlog1(self, msg): _dlog(msg, 1, self._debug)
    def _dlog2(self, msg): _dlog(msg, 2, self._debug)
    def _dlog3(self, msg): _dlog(msg, 3, self._debug)
    def _dlog4(self, msg): _dlog(msg, 4, self._debug)

    # ------------------------------------------------------------------
    # HTTP request layer
    # ------------------------------------------------------------------

    def make_request(self, operation=None, path=None, payload=None, retry=-1):
        """
        Issue a Redfish HTTP request and normalise the response.

        :returns True on success (200/202/204), raises RvmcError on failure.
        """
        self.response = None
        url = path if path is not None else self.url

        before = datetime.datetime.now().replace(microsecond=0)
        try:
            if operation == GET:
                self.response = self.redfish_obj.get(url, headers=GET_HEADERS)
            elif operation == POST:
                self.response = self.redfish_obj.post(url, body=payload,
                                                      headers=POST_HEADERS)
            elif operation == PATCH:
                self.response = self.redfish_obj.patch(url, body=payload,
                                                       headers=PATCH_HEADERS)
            else:
                raise RvmcError("Unsupported operation: %s" % operation)
        except RvmcError:
            raise
        except Exception as ex:
            raise RvmcError("Request failed on '%s': %s" % (url, ex))

        if self.response is None:
            raise RvmcError("No response from %s %s" % (operation, url))

        elapsed = (datetime.datetime.now().replace(microsecond=0) - before).seconds

        if not self._check_ok_status(url, operation, elapsed):
            if retry < 0 or retry >= MAX_HTTP_TRANSIENT_ERROR_RETRIES:
                raise RvmcError("HTTP error on %s %s" % (operation, url))
            retry += 1
            self._wlog("Transient error — retry %d/%d in %ds" %
                       (retry, MAX_HTTP_TRANSIENT_ERROR_RETRIES,
                        HTTP_REQUEST_RETRY_INTERVAL))
            time.sleep(HTTP_REQUEST_RETRY_INTERVAL)
            return self.make_request(operation=operation, path=path,
                                     payload=payload, retry=retry)

        if self.response.status == 204:
            self.response = ""
            return True

        try:
            if self._resp_dict() and self._format():
                self._dlog4("Response:\n%s\n" % self.response_json)
                return True
        except Exception as ex:
            raise RvmcError("Failed to parse %s response from '%s': %s" %
                            (operation, url, ex))

        raise RvmcError("Unparseable response from %s %s" % (operation, url))

    def _resp_dict(self):
        if self.response.read:
            try:
                self.response_dict = json.loads(self.response.read)
                return True
            except Exception as ex:
                raise RvmcError("JSON parse error: %s" % ex)
        raise RvmcError("Empty response body")

    def _format(self):
        if self._resp_dict():
            self.response_json = json.dumps(self.response_dict,
                                            indent=4, sort_keys=True)
            return True
        return False

    def get_key_value(self, key1, key2=None):
        value1 = self.response_dict.get(key1)
        if key2 is None:
            return value1
        if value1 is None:
            return None
        return value1.get(key2)

    def _check_ok_status(self, function, operation, seconds):
        # 400/403/404 from an eject POST is handled by the eject stage
        if self.response.status in [400, 403, 404] and \
                function == self.vm_eject_url and operation == POST:
            return True
        if self.response.status not in [200, 202, 204]:
            self._elog("HTTP %d: %s %s failed after %ds" %
                       (self.response.status, operation, function, seconds))
            return False
        self._dlog2("HTTP %s %s OK (%d) in %ds" %
                    (operation, function, self.response.status, seconds))
        return True

    # ------------------------------------------------------------------
    # Redfish pipeline stages
    # ------------------------------------------------------------------

    def _redfish_client_connect(self):
        self._slog('Redfish Client Connection')

        # Ping check (IPv4 and IPv6)
        ping_ok = False
        ping_count_flag = "-n 1" if sys.platform == "win32" else "-c 1"
        ping_null       = "NUL"  if sys.platform == "win32" else "/dev/null"
        for attempt in range(10):
            if self.ipv6:
                rc = os.system("ping -6 %s %s > %s 2>&1" %
                               (ping_count_flag, self.ip, ping_null))
            else:
                rc = os.system("ping %s %s > %s 2>&1" %
                               (ping_count_flag, self.ip, ping_null))
            if rc == 0:
                ping_ok = True
                break
            self._ilog("Ping retry %d/10" % (attempt + 1))
            time.sleep(2)

        if not ping_ok:
            raise RvmcConnectionError("Unable to ping BMC at %s" % self.ip)
        self._ilog("BMC Ping OK: %s" % self.ip)

        self._dlog1("Connecting to Redfish service at %s" % self.uri)
        
        for attempt in range(1, MAX_CONNECTION_ATTEMPTS + 1):
            try:
                self.redfish_obj = redfish.redfish_client(
                    base_url=self.uri,
                    username=self.un,
                    password=self.pw,
                    default_prefix=REDFISH_ROOT_PATH,
                )
                if self.redfish_obj is not None:
                    return
            except Exception as ex:
                self._wlog("Connection attempt %d/%d failed: %s" %
                           (attempt, MAX_CONNECTION_ATTEMPTS, ex))
                if attempt < MAX_CONNECTION_ATTEMPTS:
                    time.sleep(CONNECTION_RETRY_INTERVAL)

        raise RvmcConnectionError("Cannot connect to BMC at %s" % self.uri)

    def _redfish_root_query(self):
        self._slog('Root Query')
        self.make_request(operation=GET, path=None)
        self.root_query_info   = self.response_json
        self.systems_group_url = self.get_key_value('Systems', '@odata.id')

    def _redfish_create_session(self):
        self._slog('Create Communication Session')
        for attempt in range(1, MAX_SESSION_CREATION_ATTEMPTS + 1):
            try:
                self.redfish_obj.login(auth="session")
                self.session = True
                self._dlog1("Session : Open")
                return
            except InvalidCredentialsError:
                raise RvmcAuthError("Invalid BMC credentials")
            except Exception as ex:
                self._wlog("Session attempt %d/%d failed: %s" %
                           (attempt, MAX_SESSION_CREATION_ATTEMPTS, ex))
                if attempt < MAX_SESSION_CREATION_ATTEMPTS:
                    time.sleep(SESSION_CREATION_RETRY_INTERVAL)

        raise RvmcAuthError("Could not create Redfish session after %d attempts"
                            % MAX_SESSION_CREATION_ATTEMPTS)

    def _redfish_get_managers(self):
        self._slog('Get Managers')
        self.managers_group_url = self.get_key_value('Managers', '@odata.id')
        if self.managers_group_url is None:
            raise RvmcError("Managers link not found in root query response")

        self.make_request(operation=GET, path=self.managers_group_url)
        self.manager_members_list = self.get_key_value('Members')

    def _redfish_get_systems_members(self):
        self._slog('Get Systems')
        self.make_request(operation=GET, path=self.systems_group_url)
        self.systems_members_list = self.get_key_value('Members')
        if not self.systems_members_list:
            raise RvmcError("No Systems Members found at %s" %
                            self.systems_group_url)
        self.systems_members = len(self.systems_members_list)

    def _redfish_powerctl_host(self, state):
        self._slog('Power %s Host' % state)

        if self.power_state == state:
            return

        self.systems_member_url = None
        for member in self.systems_members_list:
            url = member.get('@odata.id') if member else None
            if url is None:
                continue
            self.systems_member_url = url
            self.make_request(operation=GET, path=url, retry=0)
            self.reset_action_dict = self.get_key_value(
                'Actions', '#ComputerSystem.Reset')
            if self.reset_action_dict is None:
                continue
            self.power_state = self.get_key_value('PowerState')
            if self.power_state == state:
                return
            break

        if self.reset_action_dict is None:
            raise RvmcPowerError("Systems Reset Action Dictionary not found")

        self.reset_command_url = self.reset_action_dict.get('target')
        if self.reset_command_url is None:
            raise RvmcPowerError("Reset command URL not found")

        reset_list = self.reset_action_dict.get(
            'ResetType@Redfish.AllowableValues')
        if not reset_list:
            raise RvmcPowerError("No allowable reset actions published by BMC")

        acceptable = {
            POWER_OFF: ['ForceOff', 'GracefulShutdown'],
            POWER_ON:  ['ForceOn', 'On'],
        }.get(state, ['ForceRestart', 'GracefulRestart'])

        command = next(
            (a for a in acceptable if a in reset_list), None)
        if command is None:
            raise RvmcPowerError("No acceptable power %s command in %s" %
                                 (state, reset_list))

        self.make_request(operation=POST,
                          payload={'ResetType': command},
                          path=self.reset_command_url)

        if state not in [POWER_OFF, POWER_ON]:
            return

        timeout   = int(os.environ.get('RVMC_POWER_ACTION_TIMEOUT', 840))
        start     = time.time()
        duration  = 0
        while time.time() - start < timeout and self.power_state != state:
            time.sleep(10)
            duration = int(time.time() - start)
            self.make_request(operation=GET, path=self.systems_member_url)
            self.power_state = self.get_key_value('PowerState')
            if self.power_state != state:
                self._dlog1("Waiting for Power %s (%s) %ds" %
                            (state, self.power_state, duration))

        if self.power_state != state:
            raise RvmcPowerError(
                "Power state did not reach %s after %ds" % (state, duration))
        self._ilog("Power %s verified (%ds)" % (state, duration))

    def _redfish_poweroff_host(self):
        self._redfish_powerctl_host(POWER_OFF)

    def _redfish_poweron_host(self):
        self._redfish_powerctl_host(POWER_ON)

    def _redfish_get_vm_url(self):
        self._slog('Get CD/DVD Virtual Media')

        if not self.manager_members_list:
            raise RvmcMediaError("No Manager Members found")

        for member in self.manager_members_list:
            member_url = member.get('@odata.id') if member else None
            if member_url is None:
                continue

            self.make_request(operation=GET, path=member_url)

            self.vm_group = self.get_key_value('VirtualMedia')
            if self.vm_group is None:
                continue

            self.vm_group_url = self.vm_group.get('@odata.id')
            if self.vm_group_url is None:
                raise RvmcMediaError("VirtualMedia group URL not found")

            self.make_request(operation=GET, path=self.vm_group_url)

            try:
                self.vm_members_array = self.get_key_value('Members') or []
                vm_members = len(self.vm_members_array)
            except Exception:
                vm_members = 0

            if vm_members == 0:
                raise RvmcMediaError("No Virtual Media members at %s" %
                                     self.vm_group_url)

            for vm_member in self.vm_members_array:
                self.vm_url = vm_member.get('@odata.id') if vm_member else None
                if self.vm_url is None:
                    continue
                self.make_request(operation=GET, path=self.vm_url)
                self.vm_media_types = self.get_key_value('MediaTypes') or []
                if _supported_device(self.vm_media_types):
                    self._dlog3("CD/DVD found at %s" % self.vm_url)
                    return
                self.vm_url = None

        raise RvmcMediaError("No CD/DVD Virtual Media device found")

    def _redfish_load_vm_actions(self):
        self._slog('Load Virtual Media Actions')
        if self.vm_url is None:
            raise RvmcMediaError("VM URL is None — cannot load actions")

        vm_data_type = self.get_key_value('@odata.type')
        if vm_data_type:
            parts = vm_data_type.split('.')
            self.vm_label   = parts[0]
            self.vm_version = parts[1] if len(parts) > 1 else None
            self.vm_actions = self.get_key_value('Actions') or {}
        self._dlog1("VM Version : %s  Label : %s" %
                    (self.vm_version, self.vm_label))

    def _redfish_eject_image(self):
        self._slog('Eject Current Image')
        self.make_request(operation=GET, path=self.vm_url)
        if self.get_key_value('Inserted') is False:
            return

        eject_label = '#VirtualMedia.EjectMedia'
        for attempt in range(10):
            vm_eject = self.vm_actions.get(eject_label)
            if vm_eject is None:
                raise RvmcMediaError("Eject action not found: %s" % eject_label)

            self.vm_eject_url = vm_eject.get('target')
            if self.vm_eject_url is None:
                raise RvmcMediaError("Eject target URL missing")

            self.make_request(operation=POST, payload={},
                              path=self.vm_eject_url)
            time.sleep(DELAY_2_SECS)

            for _ in range(MAX_POLL_COUNT):
                self.make_request(operation=GET, path=self.vm_url)
                if self.get_key_value('Inserted') is False:
                    self._ilog("Ejected")
                    return
                if self.get_key_value('Image'):
                    break   # image still present — retry outer loop
                time.sleep(RETRY_DELAY_SECS)

        raise RvmcMediaError("Eject timed out after 10 attempts")

    def _redfish_insert_image(self):
        self._slog('Insert Image')

        vm_insert_act = self.vm_actions.get('#VirtualMedia.InsertMedia')
        vm_insert_url = vm_insert_act.get('target') if vm_insert_act else None
        if vm_insert_url is None:
            raise RvmcMediaError("InsertMedia action URL not found")

        payload = {'Image': self.img, 'Inserted': True, 'WriteProtected': True}
        self.make_request(operation=POST, payload=payload, path=vm_insert_url)

        for poll in range(MAX_POLL_COUNT):
            self.make_request(operation=GET, path=self.vm_url)
            if self.get_key_value('Image') == self.img:
                self._ilog("Image inserted (%ds)" % (poll * RETRY_DELAY_SECS))
                return
            time.sleep(RETRY_DELAY_SECS)
            self._dlog1("Insertion wait %ds (%d/%d)" %
                        (poll * RETRY_DELAY_SECS, poll, MAX_POLL_COUNT))

        raise RvmcMediaError("Image insertion timed out")

    def _redfish_set_boot_override(self):
        self._slog('Set Boot Override to CD/DVD')

        for member in self.systems_members_list:
            url = member.get('@odata.id') if member else None
            if url is None:
                continue
            self.systems_member_url = url
            self.make_request(operation=GET, path=url)
            self.boot_control_dict = self.get_key_value('Boot')
            if self.boot_control_dict:
                break

        if not self.boot_control_dict:
            raise RvmcBootError("Boot control dict not found")

        allowable_label = 'BootSourceOverrideMode@Redfish.AllowableValues'
        mode_list = self.get_key_value('Boot', allowable_label)

        if mode_list is None:
            payload = {"Boot": {"BootSourceOverrideEnabled": "Once",
                                "BootSourceOverrideMode": "UEFI"}}
        elif "UEFI" in mode_list:
            payload = {"Boot": {"BootSourceOverrideEnabled": "Once",
                                "BootSourceOverrideTarget": "Cd"}}
        elif "Legacy" in mode_list:
            payload = {"Boot": {"BootSourceOverrideEnabled": "Once",
                                "BootSourceOverrideMode": "Legacy",
                                "BootSourceOverrideTarget": "Cd"}}
        else:
            raise RvmcBootError("Unsupported boot modes: %s" % mode_list)

        self.make_request(operation=PATCH, path=self.systems_member_url,
                          payload=payload)
        self.make_request(operation=GET,   path=self.systems_member_url)

        enabled = self.get_key_value('Boot', 'BootSourceOverrideEnabled')
        device  = self.get_key_value('Boot', 'BootSourceOverrideTarget')
        mode    = self.get_key_value('Boot', 'BootSourceOverrideMode')

        if enabled == "Once" and _supported_device(self.vm_media_types):
            self._ilog("Boot override verified [%s:%s:%s]" %
                       (enabled, device, mode))
        else:
            raise RvmcBootError("Boot override verification failed "
                                "[%s:%s:%s]" % (enabled, device, mode))

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    def execute(self, request: ToolRequest) -> ToolResult:
        """Run the full ISO injection and boot sequence."""
        self._redfish_client_connect()
        self._redfish_root_query()
        self._redfish_create_session()
        self._redfish_get_managers()
        self._redfish_get_systems_members()
        self._redfish_get_vm_url()
        self._redfish_load_vm_actions()
        self._redfish_eject_image()
        self._redfish_poweroff_host()
        self._redfish_insert_image()
        self._redfish_set_boot_override()
        self._redfish_poweron_host()
        self._ilog("Done")


###############################################################################
# Agent-facing entry point
###############################################################################

def run_rvmc(target: BmcTarget) -> ToolResult:
    """
    Execute the full RVMC pipeline for a single BMC target.

    Returns a ToolResult — never calls sys.exit.  The agent inspects
    result.status for branching and result.stderr for error detail.

    :param target: fully populated BmcTarget (caller resolves credentials)
    :returns: ToolResult with ResultStatus and structured data
    """
    import time as _time
    start = _time.time()

    try:
        with VmcObject(target) as vmc:
            vmc.execute()
        return ToolResult(
            status=ResultStatus.SUCCESS,
            exit_code=0,
            stdout="ISO injection complete for %s" % (target.target_name or target.address),            duration_seconds=_time.time() - start,
            data={"target": target.target_name, "address": target.address,
                  "image": target.image},
        )
    except RvmcAuthError as ex:
        return ToolResult.error(ResultStatus.AUTH_ERROR, ex.message)
    except RvmcConnectionError as ex:
        return ToolResult.error(ResultStatus.NOT_CONNECTED, ex.message)
    except RvmcError as ex:
        return ToolResult.error(ResultStatus.FAILURE, ex.message)
    except Exception as ex:
        return ToolResult.error(ResultStatus.FAILURE, "Unexpected error: %s" % ex)


###############################################################################
# CLI shim — file-based config lives here only
###############################################################################

if __name__ == '__main__':
    import argparse
    import base64
    import yaml

    CONFIG_FILE = 'inventory/rvmc.yaml'

    parser = argparse.ArgumentParser(description=FEATURE_NAME)
    parser.add_argument("--target", type=str, required=False)
    parser.add_argument("--debug",  type=int, required=False, default=0)
    args = parser.parse_args()

    targets = []
    if args.target and args.target != 'None':
        targets = args.target.split(',')

    if not os.path.exists(CONFIG_FILE):
        _elog("Config file not found: %s" % CONFIG_FILE)
        sys.exit(1)

    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = yaml.safe_load(f)
    except Exception as ex:
        _elog("Cannot read config file: %s" % ex)
        sys.exit(1)

    bmc_targets = []
    found = False
    for section in cfg:
        if section == PRIMARY_CONFIG_LABEL:
            found = True
            resolved = targets or list(cfg[section].keys())
            for tname in resolved:
                try:
                    bmc_targets.append(
                        BmcTarget.from_config(tname, cfg[section][tname],
                                              debug=args.debug))
                except (ValueError, KeyError) as ex:
                    _elog("Skipping target '%s': %s" % (tname, ex))

    if not found:
        try:
            bmc_targets.append(BmcTarget.from_config(None, cfg,
                                                     debug=args.debug))
        except ValueError as ex:
            _elog("Config parse error: %s" % ex)
            sys.exit(1)

    if not bmc_targets:
        _elog("No valid BMC targets found in %s" % CONFIG_FILE)
        sys.exit(1)

    exit_code = 0
    for t in bmc_targets:
        result = run_rvmc(t)
        sys.stdout.write("\n%s\n" % json.dumps(result.to_dict(), indent=2))
        if not result.success:
            exit_code = 1

    sys.exit(exit_code)
