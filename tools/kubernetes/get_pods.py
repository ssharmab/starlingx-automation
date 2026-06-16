# SPDX-License-Identifier: Apache-2.0
"""
get_pods.py
-----------
Kubernetes workload inspection tool.

LAYER: Tool
  Provides read-only workload queries over an SSH transport.
  All commands are static strings — no external input is interpolated.

Tools exposed:
  GetPodsTool.get_pods()             — all pods, wide output
  GetPodsTool.get_failed_pods()      — pods not in Running or Succeeded state
  GetPodsTool.get_pod_resource_usage() — CPU/memory per pod (metrics-server)
  GetPodsTool.get_deployments()      — all deployments with replica counts
  GetPodsTool.get_replicasets()      — all ReplicaSets
  GetPodsTool.get_statefulsets()     — all StatefulSets
  GetPodsTool.get_daemonsets()       — all DaemonSets
  GetPodsTool.get_jobs()             — all Jobs
  GetPodsTool.get_cronjobs()         — all CronJobs
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.kubernetes.base import KubernetesTool, load_inventory, _build_connection
from utils.tool_result import ToolResult

logger = logging.getLogger(__name__)


class GetPodsTool(KubernetesTool):
    """
    Read-only Kubernetes workload inspection tool.

    All methods accept an optional namespace override.  Pass
    "--all-namespaces" to query across all namespaces.
    """

    name: str = "get_pods"
    description: str = "Returns pod status, resource usage, deployments, and workload health."

    def execute(self, correlation_id: str | None = None) -> ToolResult:
        """Run the default pod listing and return results."""
        return self.get_pods(correlation_id=correlation_id)

    def get_pods(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all pods with status, restarts, age, IP, and node placement.

        Args:
            namespace: Namespace override, or None to use the instance default.

        Returns:
            ToolResult.stdout contains kubectl get pods -o wide table.
        """
        return self._run(
            f"kubectl get pods {self._ns_flag(namespace)} -o wide",
            correlation_id,
        )

    def get_failed_pods(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return pods not in Running or Succeeded state.

        Agents use this as a fast-path health signal — no output means
        all pods are healthy.

        Args:
            namespace: Namespace override, or None to use the instance default.

        Returns:
            ToolResult.stdout is empty when all pods are healthy.
        """
        return self._run(
            f"kubectl get pods {self._ns_flag(namespace)} "
            "--field-selector=status.phase!=Running,status.phase!=Succeeded",
            correlation_id,
        )

    def get_pod_resource_usage(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return CPU and memory consumption per pod.

        Requires metrics-server.  Returns ResultStatus.UNAVAILABLE if absent.

        Args:
            namespace: Namespace override, or None to use the instance default.

        Returns:
            ToolResult.stdout contains kubectl top pods table.
        """
        return self._run(
            f"kubectl top pods {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_deployments(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all Deployments with desired/ready/available replica counts.

        Args:
            namespace: Namespace override, or None to use the instance default.

        Returns:
            ToolResult.stdout contains kubectl get deployments table.
        """
        return self._run(
            f"kubectl get deployments {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_replicasets(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all ReplicaSets with desired/current/ready counts.

        Args:
            namespace: Namespace override, or None to use the instance default.

        Returns:
            ToolResult.stdout contains kubectl get replicasets table.
        """
        return self._run(
            f"kubectl get replicasets {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_statefulsets(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all StatefulSets with ready/desired counts.

        Args:
            namespace: Namespace override, or None to use the instance default.

        Returns:
            ToolResult.stdout contains kubectl get statefulsets table.
        """
        return self._run(
            f"kubectl get statefulsets {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_daemonsets(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all DaemonSets with desired/current/ready/available counts.

        Args:
            namespace: Namespace override, or None to use the instance default.

        Returns:
            ToolResult.stdout contains kubectl get daemonsets table.
        """
        return self._run(
            f"kubectl get daemonsets {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_jobs(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all Jobs with completions and duration.

        Args:
            namespace: Namespace override, or None to use the instance default.

        Returns:
            ToolResult.stdout contains kubectl get jobs table.
        """
        return self._run(
            f"kubectl get jobs {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_cronjobs(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all CronJobs with schedule, last-schedule, and active count.

        Args:
            namespace: Namespace override, or None to use the instance default.

        Returns:
            ToolResult.stdout contains kubectl get cronjobs table.
        """
        return self._run(
            f"kubectl get cronjobs {self._ns_flag(namespace)}",
            correlation_id,
        )


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
    print("  GetPodsTool — test harness")
    print("=" * 60)

    try:
        config = load_inventory()
    except InventoryError as exc:
        logger.error("Inventory validation failed [%s]: %s", exc.code.value, exc)
        sys.exit(1)

    conn = _build_connection(config)
    try:
        tool = GetPodsTool.from_inventory(config, conn)

        tests = [
            ("get_pods",               lambda: tool.get_pods()),
            ("get_failed_pods",        lambda: tool.get_failed_pods()),
            ("get_pod_resource_usage", lambda: tool.get_pod_resource_usage()),
            ("get_deployments",        lambda: tool.get_deployments()),
            ("get_replicasets",        lambda: tool.get_replicasets()),
            ("get_statefulsets",       lambda: tool.get_statefulsets()),
            ("get_daemonsets",         lambda: tool.get_daemonsets()),
            ("get_jobs",               lambda: tool.get_jobs()),
            ("get_cronjobs",           lambda: tool.get_cronjobs()),
            # Cross-namespace variant
            ("get_pods (all ns)",      lambda: tool.get_pods(namespace="--all-namespaces")),
        ]

        for name, fn in tests:
            result = fn()
            tag = f"[{result.status.value.upper()}]"
            print(f"\n--- {name} {tag} ({result.duration_seconds:.2f}s) ---")
            print(result.stdout or result.stderr or "(no output)")

        print("\n" + "=" * 60)
        print("  All GetPodsTool tests complete.")
        print("=" * 60)

    finally:
        conn.disconnect()
