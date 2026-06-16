# SPDX-License-Identifier: Apache-2.0
"""Tests for tools/kubernetes/base.py — full branch coverage."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.tool_result import ToolResult, ResultStatus
from utils.ssh_connection import SSHConnection

_INVENTORY_PATH = (
    Path(__file__).parent.parent.parent / "inventory" / "inventory.yaml"
)


@pytest.fixture(scope="module")
def inventory():
    from utils.inventory_checker import InventoryChecker
    return InventoryChecker(
        path=_INVENTORY_PATH,
        check_reachability=False,
        check_ssh_access=False,
    ).validate()


def _mock_conn():
    conn = MagicMock(spec=SSHConnection)
    conn.__class__ = SSHConnection
    return conn


class TestKubernetesToolInit:
    def test_valid_construction(self, inventory):
        from tools.kubernetes.get_nodes import GetNodesTool
        conn = _mock_conn()
        tool = GetNodesTool(conn, namespace=inventory.namespace,
                            kubeconfig=inventory.kubeconfig)
        assert tool.namespace == inventory.namespace
        assert "KUBECONFIG=%s" % inventory.kubeconfig in tool._env_prefix

    def test_no_kubeconfig_no_prefix(self):
        from tools.kubernetes.get_nodes import GetNodesTool
        conn = _mock_conn()
        tool = GetNodesTool(conn)
        assert tool._env_prefix == ""

    def test_wrong_conn_type_raises(self):
        from tools.kubernetes.base import KubernetesTool
        with pytest.raises(TypeError, match="SSHConnection"):
            # Use a concrete subclass to hit the isinstance check
            from tools.kubernetes.get_nodes import GetNodesTool
            GetNodesTool("not-a-conn")

    def test_invalid_kubeconfig_raises(self, inventory):
        from tools.kubernetes.get_nodes import GetNodesTool
        conn = _mock_conn()
        with pytest.raises(ValueError, match="invalid characters"):
            GetNodesTool(conn, kubeconfig=inventory.kubeconfig + "; rm -rf /")

    def test_from_inventory(self, inventory):
        from tools.kubernetes.get_nodes import GetNodesTool
        conn = _mock_conn()
        tool = GetNodesTool.from_inventory(inventory, conn)
        assert tool.namespace == inventory.namespace

    def test_cannot_instantiate_abstract_base(self):
        from tools.kubernetes.base import KubernetesTool
        with pytest.raises(TypeError, match="abstract"):
            KubernetesTool(_mock_conn())


class TestNsFlag:
    def test_regular_namespace(self):
        from tools.kubernetes.base import KubernetesTool
        conn = _mock_conn()
        tool = KubernetesTool(conn, namespace="default")
        assert tool._ns_flag(None)          == "-n default"
        assert tool._ns_flag("custom")      == "-n custom"

    def test_all_namespaces(self):
        from tools.kubernetes.base import KubernetesTool
        conn = _mock_conn()
        tool = KubernetesTool(conn)
        assert tool._ns_flag("--all-namespaces") == "--all-namespaces"


class TestRunMethod:
    def _tool(self):
        from tools.kubernetes.base import KubernetesTool
        conn = _mock_conn()
        return KubernetesTool(conn), conn

    def test_success(self):
        tool, conn = self._tool()
        conn.execute.return_value = ToolResult(
            status=ResultStatus.SUCCESS, exit_code=0, stdout="nodes", stderr="")
        result = tool._run("kubectl get nodes")
        assert result.success is True
        assert result.stdout == "nodes"

    def test_memcache_noise_stripped_and_success(self):
        tool, conn = self._tool()
        conn.execute.return_value = ToolResult(
            status=ResultStatus.FAILURE, exit_code=1,
            stdout="pod1   Running",
            stderr="couldn't get current server API group list\ncouldn't get current server API group list",
        )
        result = tool._run("kubectl get pods")
        assert result.status == ResultStatus.SUCCESS
        assert result.stderr == ""

    def test_unavailable_pattern_maps_to_unavailable(self):
        tool, conn = self._tool()
        conn.execute.return_value = ToolResult(
            status=ResultStatus.FAILURE, exit_code=1,
            stdout="",
            stderr="the server doesn't have a resource type",
        )
        result = tool._run("kubectl get ingresses")
        assert result.status == ResultStatus.UNAVAILABLE

    def test_no_matches_for_kind(self):
        tool, conn = self._tool()
        conn.execute.return_value = ToolResult(
            status=ResultStatus.FAILURE, exit_code=1,
            stdout="", stderr="no matches for kind",
        )
        result = tool._run("kubectl get crd")
        assert result.status == ResultStatus.UNAVAILABLE

    def test_genuine_failure_preserved(self):
        tool, conn = self._tool()
        conn.execute.return_value = ToolResult(
            status=ResultStatus.FAILURE, exit_code=1,
            stdout="", stderr="connection refused",
        )
        result = tool._run("kubectl get pods")
        assert result.status == ResultStatus.FAILURE
        assert result.stderr == "connection refused"

    def test_env_prefix_prepended(self):
        from tools.kubernetes.base import KubernetesTool
        conn = _mock_conn()
        tool = KubernetesTool(conn, kubeconfig="/etc/kube/config")
        conn.execute.return_value = ToolResult(
            status=ResultStatus.SUCCESS, exit_code=0, stdout="ok", stderr="")
        tool._run("kubectl get nodes", "cid-1")
        called_cmd = conn.execute.call_args[0][0]
        assert called_cmd.startswith("export KUBECONFIG=/etc/kube/config")
