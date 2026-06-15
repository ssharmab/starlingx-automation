# SPDX-License-Identifier: Apache-2.0
"""
get_events.py
-------------
Kubernetes event and health inspection tool.

LAYER: Tool
  Provides read-only event and health queries over an SSH transport.
  All commands are static strings — no external input is interpolated.

Tools exposed:
  GetEventsTool.get_events()          — all events sorted by lastTimestamp
  GetEventsTool.get_warning_events()  — only Warning-type events
  GetEventsTool.get_resource_quotas() — ResourceQuotas showing used vs limits
  GetEventsTool.get_services()        — services with type, IPs, and ports
  GetEventsTool.get_ingresses()       — Ingress resources
  GetEventsTool.get_endpoints()       — Endpoints showing pod IPs per service
  GetEventsTool.get_network_policies() — NetworkPolicy resources
  GetEventsTool.get_persistent_volumes() — cluster-scoped PVs
  GetEventsTool.get_persistent_volume_claims() — PVCs per namespace
  GetEventsTool.get_storage_classes() — StorageClasses with provisioner
  GetEventsTool.get_configmaps()      — ConfigMaps with key counts
  GetEventsTool.get_secrets()         — Secrets (metadata only, no values)
  GetEventsTool.get_service_accounts() — ServiceAccounts
  GetEventsTool.get_roles()           — namespace-scoped RBAC Roles
  GetEventsTool.get_cluster_roles()   — cluster-scoped ClusterRoles
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools.kubernetes.base import KubernetesTool, load_inventory, _build_connection
from utils.tool_result import ToolResult

logger = logging.getLogger(__name__)


class GetEventsTool(KubernetesTool):
    """
    Read-only Kubernetes event, health, network, storage, and RBAC tool.

    Events are the primary signal for agent triage workflows.  Warning
    events, combined with failed pod lists, give the agent enough context
    to determine remediation priority without querying individual pod logs.
    """

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def get_events(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all events sorted by lastTimestamp, most recent last.

        Agents use this to identify crash loops, image pull failures,
        OOMKills, and scheduling failures.

        Args:
            namespace: Namespace override, or None to use the instance default.

        Returns:
            ToolResult.stdout contains kubectl get events table.
        """
        return self._run(
            f"kubectl get events {self._ns_flag(namespace)} "
            "--sort-by='.lastTimestamp'",
            correlation_id,
        )

    def get_warning_events(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return only Warning-type events sorted by lastTimestamp.

        This is the fast-path triage signal: if this returns no output,
        the cluster is nominally healthy from an event perspective.

        Args:
            namespace: Namespace override, or None to use the instance default.

        Returns:
            ToolResult.stdout contains Warning events only, or empty.
        """
        return self._run(
            f"kubectl get events {self._ns_flag(namespace)} "
            "--field-selector=type=Warning "
            "--sort-by='.lastTimestamp'",
            correlation_id,
        )

    def get_resource_quotas(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all ResourceQuotas showing used vs hard limits.

        Args:
            namespace: Namespace override, or None to use the instance default.

        Returns:
            ToolResult.stdout contains kubectl get resourcequotas table.
        """
        return self._run(
            f"kubectl get resourcequotas {self._ns_flag(namespace)}",
            correlation_id,
        )

    # ------------------------------------------------------------------
    # Networking
    # ------------------------------------------------------------------

    def get_services(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all Services with type, cluster-IP, external-IP, and ports.

        Args:
            namespace: Namespace override, or None to use the instance default.
        """
        return self._run(
            f"kubectl get services {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_ingresses(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all Ingress resources with hosts, addresses, and ports.

        Args:
            namespace: Namespace override, or None to use the instance default.
        """
        return self._run(
            f"kubectl get ingresses {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_endpoints(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all Endpoints showing pod IPs backing each service.

        Args:
            namespace: Namespace override, or None to use the instance default.
        """
        return self._run(
            f"kubectl get endpoints {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_network_policies(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all NetworkPolicy resources governing pod-to-pod traffic.

        Args:
            namespace: Namespace override, or None to use the instance default.
        """
        return self._run(
            f"kubectl get networkpolicies {self._ns_flag(namespace)}",
            correlation_id,
        )

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def get_persistent_volumes(self, correlation_id: str | None = None) -> ToolResult:
        """Return all PersistentVolumes (cluster-scoped) with capacity and status."""
        return self._run("kubectl get pv", correlation_id)

    def get_persistent_volume_claims(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all PersistentVolumeClaims with status and capacity.

        Args:
            namespace: Namespace override, or None to use the instance default.
        """
        return self._run(
            f"kubectl get pvc {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_storage_classes(self, correlation_id: str | None = None) -> ToolResult:
        """Return all StorageClasses with provisioner and reclaim policy."""
        return self._run("kubectl get storageclasses", correlation_id)

    # ------------------------------------------------------------------
    # Configuration & RBAC
    # ------------------------------------------------------------------

    def get_configmaps(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all ConfigMaps with data-key counts.

        Args:
            namespace: Namespace override, or None to use the instance default.
        """
        return self._run(
            f"kubectl get configmaps {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_secrets(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all Secrets with type and key counts.

        Secret values are NEVER decoded or included in output.

        Args:
            namespace: Namespace override, or None to use the instance default.
        """
        return self._run(
            f"kubectl get secrets {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_service_accounts(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all ServiceAccounts.

        Args:
            namespace: Namespace override, or None to use the instance default.
        """
        return self._run(
            f"kubectl get serviceaccounts {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_roles(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> ToolResult:
        """
        Return all namespace-scoped RBAC Roles.

        Args:
            namespace: Namespace override, or None to use the instance default.
        """
        return self._run(
            f"kubectl get roles {self._ns_flag(namespace)}",
            correlation_id,
        )

    def get_cluster_roles(self, correlation_id: str | None = None) -> ToolResult:
        """Return all cluster-scoped ClusterRoles."""
        return self._run("kubectl get clusterroles", correlation_id)


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
    print("  GetEventsTool — test harness")
    print("=" * 60)

    try:
        config = load_inventory()
    except InventoryError as exc:
        logger.error("Inventory validation failed [%s]: %s", exc.code.value, exc)
        sys.exit(1)

    conn = _build_connection(config)
    try:
        tool = GetEventsTool.from_inventory(config, conn)

        tests = [
            ("get_events",                  lambda: tool.get_events()),
            ("get_warning_events",          lambda: tool.get_warning_events()),
            ("get_resource_quotas",         lambda: tool.get_resource_quotas()),
            ("get_services",                lambda: tool.get_services()),
            ("get_ingresses",               lambda: tool.get_ingresses()),
            ("get_endpoints",               lambda: tool.get_endpoints()),
            ("get_network_policies",        lambda: tool.get_network_policies()),
            ("get_persistent_volumes",      lambda: tool.get_persistent_volumes()),
            ("get_persistent_volume_claims", lambda: tool.get_persistent_volume_claims()),
            ("get_storage_classes",         lambda: tool.get_storage_classes()),
            ("get_configmaps",              lambda: tool.get_configmaps()),
            ("get_secrets",                 lambda: tool.get_secrets()),
            ("get_service_accounts",        lambda: tool.get_service_accounts()),
            ("get_roles",                   lambda: tool.get_roles()),
            ("get_cluster_roles",           lambda: tool.get_cluster_roles()),
        ]

        for name, fn in tests:
            result = fn()
            tag = f"[{result.status.value.upper()}]"
            print(f"\n--- {name} {tag} ({result.duration_seconds:.2f}s) ---")
            print(result.stdout or result.stderr or "(no output)")

        print("\n" + "=" * 60)
        print("  All GetEventsTool tests complete.")
        print("=" * 60)

    finally:
        conn.disconnect()
