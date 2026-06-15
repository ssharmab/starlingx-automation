# SPDX-License-Identifier: Apache-2.0
"""
k8s_check.py
------------
Full-suite Kubernetes diagnostic orchestrator.

LAYER: Tool / Orchestration boundary
  This module is the entry point for running ALL Kubernetes checks as a
  single suite.  It delegates every individual check to the focused tool
  classes in tools/kubernetes/ rather than re-implementing commands here.

  Individual tools should be used directly by LangGraph nodes that need
  a specific check.  This module exists for:
    - Full cluster health sweeps at workflow start.
    - Human-readable CLI output during development.
    - Baseline snapshot collection before and after changes.

REFACTORING NOTE:
  All command logic has been moved to:
    tools/kubernetes/get_nodes.py   — node, cluster, namespace checks
    tools/kubernetes/get_pods.py    — workload checks
    tools/kubernetes/get_events.py  — events, networking, storage, RBAC
    tools/kubernetes/get_logs.py    — pod log retrieval

  K8sChecker now composes those tools rather than duplicating their logic.
"""

from __future__ import annotations

import logging
import socket
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).parent))

from tools.kubernetes.get_nodes import GetNodesTool
from tools.kubernetes.get_pods import GetPodsTool
from tools.kubernetes.get_events import GetEventsTool
from utils.inventory_checker import InventoryChecker, InventoryConfig, InventoryError
from utils.ssh_connection import SSHConnection, HostKeyPolicy
from utils.tool_result import ToolResult, ResultStatus

logger = logging.getLogger(__name__)

_DEFAULT_SUITE_TIMEOUT = 600


@dataclass
class CheckSuiteResult:
    """
    Aggregated result of a full K8s check suite run.

    Attributes:
        results:          ToolResult per check label.
        overall_success:  True iff all checks are SUCCESS or UNAVAILABLE.
        failed_checks:    Labels of checks with non-success/unavailable status.
        duration_seconds: Wall-clock time for the entire suite.
        correlation_id:   Links this suite to a LangGraph run or audit record.
    """
    results: dict[str, ToolResult] = field(default_factory=dict)
    overall_success: bool = False
    failed_checks: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        """JSON-serialisable summary for OpenAI tool responses."""
        return {
            "overall_success": self.overall_success,
            "failed_checks": self.failed_checks,
            "duration_seconds": round(self.duration_seconds, 3),
            "correlation_id": self.correlation_id,
            "results": {k: v.to_dict() for k, v in self.results.items()},
        }


class K8sChecker:
    """
    Full-suite Kubernetes diagnostic orchestrator.

    Composes GetNodesTool, GetPodsTool, and GetEventsTool to run all
    available checks in a single pass with per-check exception isolation
    and a suite-level wall-clock timeout.

    Construct via from_inventory() to guarantee all parameters come from
    a validated, type-safe source.
    """

    def __init__(
        self,
        conn: SSHConnection,
        namespace: str = "default",
        kubeconfig: str | None = None,
        suite_timeout: int = _DEFAULT_SUITE_TIMEOUT,
    ) -> None:
        self._nodes = GetNodesTool(conn, namespace=namespace, kubeconfig=kubeconfig)
        self._pods = GetPodsTool(conn, namespace=namespace, kubeconfig=kubeconfig)
        self._events = GetEventsTool(conn, namespace=namespace, kubeconfig=kubeconfig)
        self.suite_timeout = suite_timeout
        self.namespace = namespace

    @classmethod
    def from_inventory(
        cls,
        config: InventoryConfig,
        conn: SSHConnection,
        suite_timeout: int = _DEFAULT_SUITE_TIMEOUT,
    ) -> "K8sChecker":
        """Construct K8sChecker from a validated InventoryConfig."""
        return cls(
            conn=conn,
            namespace=config.namespace,
            kubeconfig=config.kubeconfig,
            suite_timeout=suite_timeout,
        )

    def run_full_check(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> CheckSuiteResult:
        """
        Run all checks with per-check isolation and suite-level timeout.

        Each check is wrapped in a try/except so a single unexpected failure
        does not discard partial results.  The suite stops if the wall-clock
        budget is exceeded.

        Args:
            namespace:      Namespace override for namespaced checks.
            correlation_id: Trace ID propagated to all child ToolResults.

        Returns:
            CheckSuiteResult with results, overall_success, failed_checks,
            duration, and correlation_id.
        """
        cid = correlation_id or str(uuid.uuid4())
        ns = namespace or self.namespace
        suite_start = time.monotonic()
        logger.info("Starting full K8s check suite. correlation_id=%s", cid)

        checks: dict[str, object] = {
            # Nodes / cluster
            "Cluster Info":             lambda: self._nodes.get_cluster_info(cid),
            "Nodes":                    lambda: self._nodes.get_nodes(cid),
            "Node Resource Usage":      lambda: self._nodes.get_node_resource_usage(cid),
            "Component Statuses":       lambda: self._nodes.get_component_statuses(cid),
            "Namespaces":               lambda: self._nodes.get_namespaces(cid),
            "API Resources":            lambda: self._nodes.get_api_resources(cid),
            # Workloads
            "Pods":                     lambda: self._pods.get_pods(ns, cid),
            "Pod Resource Usage":       lambda: self._pods.get_pod_resource_usage(ns, cid),
            "Failed Pods":              lambda: self._pods.get_failed_pods(ns, cid),
            "Deployments":              lambda: self._pods.get_deployments(ns, cid),
            "ReplicaSets":              lambda: self._pods.get_replicasets(ns, cid),
            "StatefulSets":             lambda: self._pods.get_statefulsets(ns, cid),
            "DaemonSets":               lambda: self._pods.get_daemonsets(ns, cid),
            "Jobs":                     lambda: self._pods.get_jobs(ns, cid),
            "CronJobs":                 lambda: self._pods.get_cronjobs(ns, cid),
            # Events & health
            "Events":                   lambda: self._events.get_events(ns, cid),
            "Warning Events":           lambda: self._events.get_warning_events(ns, cid),
            "Resource Quotas":          lambda: self._events.get_resource_quotas(ns, cid),
            # Networking
            "Services":                 lambda: self._events.get_services(ns, cid),
            "Ingresses":                lambda: self._events.get_ingresses(ns, cid),
            "Endpoints":                lambda: self._events.get_endpoints(ns, cid),
            "Network Policies":         lambda: self._events.get_network_policies(ns, cid),
            # Storage
            "Persistent Volumes":       lambda: self._events.get_persistent_volumes(cid),
            "Persistent Volume Claims": lambda: self._events.get_persistent_volume_claims(ns, cid),
            "Storage Classes":          lambda: self._events.get_storage_classes(cid),
            # Config & RBAC
            "ConfigMaps":               lambda: self._events.get_configmaps(ns, cid),
            "Secrets":                  lambda: self._events.get_secrets(ns, cid),
            "Service Accounts":         lambda: self._events.get_service_accounts(ns, cid),
            "Roles":                    lambda: self._events.get_roles(ns, cid),
            "Cluster Roles":            lambda: self._events.get_cluster_roles(cid),
        }

        results: dict[str, ToolResult] = {}
        failed: list[str] = []

        for label, fn in checks.items():
            if time.monotonic() - suite_start >= self.suite_timeout:
                logger.error(
                    "Suite timeout (%ds) exceeded. Remaining checks skipped. cid=%s",
                    self.suite_timeout, cid,
                )
                break

            logger.info("Check: %s", label)
            try:
                result = fn()
            except Exception as exc:
                logger.error("Check '%s' raised unexpected exception: %s", label, exc)
                result = ToolResult.error(
                    ResultStatus.FAILURE,
                    f"Unexpected exception: {exc}",
                    correlation_id=cid,
                )

            results[label] = result
            if result.status not in (ResultStatus.SUCCESS, ResultStatus.UNAVAILABLE):
                failed.append(label)

        duration = time.monotonic() - suite_start
        logger.info(
            "Suite complete. passed=%d/%d failed=%s duration=%.1fs cid=%s",
            len(results) - len(failed), len(results), failed or "none", duration, cid,
        )

        return CheckSuiteResult(
            results=results,
            overall_success=len(failed) == 0,
            failed_checks=failed,
            duration_seconds=duration,
            correlation_id=cid,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the full Kubernetes check suite using inventory.yaml."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    try:
        config = InventoryChecker().validate()
    except InventoryError as exc:
        logger.error("Inventory validation failed [%s]: %s", exc.code.value, exc)
        return

    try:
        with SSHConnection(
            host=config.host,
            login=config.login,
            password=config.password,
            host_key_policy=HostKeyPolicy.TRUST_ON_FIRST_USE,
        ) as conn:
            checker = K8sChecker.from_inventory(config, conn)
            suite = checker.run_full_check()

            for label, result in suite.results.items():
                tag = f"[{result.status.value.upper()}]"
                print(f"\n{'=' * 60}")
                print(f"  {tag} {label}  ({result.duration_seconds:.2f}s)")
                print("=" * 60)
                print(result.stdout or result.stderr or "(no output)")

            print(f"\n{'=' * 60}")
            print(
                f"  Suite: {'SUCCESS' if suite.overall_success else 'FAILED'} "
                f"| {len(suite.results) - len(suite.failed_checks)}/{len(suite.results)} passed "
                f"| {suite.duration_seconds:.1f}s"
            )
            if suite.failed_checks:
                print(f"  Failed: {suite.failed_checks}")
            print("=" * 60)

    except ConnectionAbortedError as exc:
        logger.error("Aborted: %s", exc)
    except socket.timeout:
        logger.error("Connection to '%s' timed out.", config.host)
    except paramiko.AuthenticationException:
        logger.error("Authentication failed for '%s' on '%s'.", config.login, config.host)


if __name__ == "__main__":
    main()
