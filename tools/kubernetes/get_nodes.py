# SPDX-License-Identifier: Apache-2.0
"""
get_nodes.py
------------
Kubernetes node inspection tool.

LAYER: Tool
  Provides read-only node checks over an SSH transport.
  All commands are static strings — no external input is interpolated.

Tools exposed:
  GetNodesTool.get_nodes()             — all nodes, wide output
  GetNodesTool.get_node_resource_usage() — CPU/memory per node (metrics-server)
  GetNodesTool.get_component_statuses()  — scheduler, controller-manager, etcd
  GetNodesTool.get_cluster_info()        — control-plane and CoreDNS endpoints
  GetNodesTool.get_namespaces()          — all namespaces
  GetNodesTool.get_api_resources()       — all registered API resource types
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow running as __main__ from any working directory.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.kubernetes.base import KubernetesTool, load_inventory, _build_connection
from utils.tool_result import ToolResult

logger = logging.getLogger(__name__)


class GetNodesTool(KubernetesTool):
    """
    Read-only Kubernetes node and cluster inspection tool.

    Every method returns a ToolResult.  Agents branch on result.status
    (ResultStatus enum) — never on string parsing.
    """

    def get_nodes(self, correlation_id: str | None = None) -> ToolResult:
        """
        Return all cluster nodes with status, roles, age, and version.

        Returns:
            ToolResult.stdout contains kubectl get nodes -o wide table.
        """
        return self._run("kubectl get nodes -o wide", correlation_id)

    def get_node_resource_usage(self, correlation_id: str | None = None) -> ToolResult:
        """
        Return CPU and memory consumption per node.

        Requires metrics-server to be installed on the cluster.
        Returns ResultStatus.UNAVAILABLE if metrics-server is absent.

        Returns:
            ToolResult.stdout contains kubectl top nodes table.
        """
        return self._run("kubectl top nodes", correlation_id)

    def get_component_statuses(self, correlation_id: str | None = None) -> ToolResult:
        """
        Return health status of scheduler, controller-manager, and etcd.

        Returns:
            ToolResult.stdout contains kubectl get componentstatuses table.
        """
        return self._run("kubectl get componentstatuses", correlation_id)

    def get_cluster_info(self, correlation_id: str | None = None) -> ToolResult:
        """
        Return cluster control-plane and CoreDNS endpoint addresses.

        Returns:
            ToolResult.stdout contains kubectl cluster-info output.
        """
        return self._run("kubectl cluster-info", correlation_id)

    def get_namespaces(self, correlation_id: str | None = None) -> ToolResult:
        """
        Return all namespaces with their status and age.

        Returns:
            ToolResult.stdout contains kubectl get namespaces table.
        """
        return self._run("kubectl get namespaces", correlation_id)

    def get_api_resources(self, correlation_id: str | None = None) -> ToolResult:
        """
        Return all API resource types registered in the cluster.

        Useful for discovering what resource types are available before
        issuing targeted queries.

        Returns:
            ToolResult.stdout contains kubectl api-resources table.
        """
        return self._run("kubectl api-resources", correlation_id)


# ---------------------------------------------------------------------------
# __main__ test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    from utils.inventory_checker import InventoryError

    print("=" * 60)
    print("  GetNodesTool — test harness")
    print("=" * 60)

    try:
        config = load_inventory()
    except InventoryError as exc:
        logger.error("Inventory validation failed [%s]: %s", exc.code.value, exc)
        sys.exit(1)

    conn = _build_connection(config)
    try:
        tool = GetNodesTool.from_inventory(config, conn)

        tests = [
            ("get_nodes",             tool.get_nodes),
            ("get_node_resource_usage", tool.get_node_resource_usage),
            ("get_component_statuses",  tool.get_component_statuses),
            ("get_cluster_info",        tool.get_cluster_info),
            ("get_namespaces",          tool.get_namespaces),
            ("get_api_resources",       tool.get_api_resources),
        ]

        for name, fn in tests:
            result = fn()
            tag = f"[{result.status.value.upper()}]"
            print(f"\n--- {name} {tag} ({result.duration_seconds:.2f}s) ---")
            print(result.stdout or result.stderr or "(no output)")

        print("\n" + "=" * 60)
        print("  All GetNodesTool tests complete.")
        print("=" * 60)

    finally:
        conn.disconnect()
