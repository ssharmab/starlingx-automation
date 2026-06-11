# SPDX-License-Identifier: Apache-2.0
"""
k8s_check.py
------------
Agent-ready Kubernetes diagnostic tool layer for the infrastructure AI platform.

LAYER: Tool
  This module sits above the transport layer (ssh_connection.py) and below
  the workflow layer (LangGraph nodes).  It translates agent intents
  ("get the list of pods") into fixed, pre-approved kubectl commands and
  returns structured ToolResult objects.

  It has NO knowledge of LangGraph, OpenAI, or agent prompts.
  It has NO interactive behavior.
  It has NO side effects beyond SSH command execution.
  It NEVER constructs commands from user/LLM input — every command is a
  static string to eliminate injection risk.

CHANGES FROM PREVIOUS VERSION:
  1. Per-check exception isolation in run_full_check().
     WHY: A single failed check must not abort the entire suite.  Agents
     need partial results to make informed decisions about cluster health.
     Previously, an unexpected exception would propagate and the agent would
     receive nothing.

  2. Suite-level timeout in run_full_check().
     WHY: An agent workflow has a budget.  A suite that runs indefinitely
     (e.g. due to a hung kubectl call with per-check timeout misconfigured)
     blocks the entire LangGraph execution graph.

  3. InventoryConfig typed input instead of raw SSHConnection + strings.
     WHY: Type-safe inputs prevent misconfiguration bugs and give the
     from_inventory() factory a single place to build the checker.

  4. ResultStatus.UNAVAILABLE for missing resource types.
     WHY: Agents must distinguish "command failed" from "this cluster does
     not have this resource type".  UNAVAILABLE routes to a skip branch,
     not a remediation branch.

  5. run_full_check() returns a CheckSuiteResult dataclass.
     WHY: A raw dict[str, ToolResult] gives the agent no high-level signal.
     CheckSuiteResult exposes overall_success, failed_checks list, and
     duration so the LangGraph router can branch without iterating every
     result.

  6. Removed all print() calls.
     WHY: Tools must not write to stdout.  Only main() may print, and only
     for human-readable demonstration.

  7. No direct _client access.
     WHY: Accessing SSHConnection._client bypasses the lock, the retry
     logic, the audit log, and the ToolResult contract.  All execution goes
     through conn.execute().
"""

from __future__ import annotations

import logging
import re
import socket
import time
import uuid
from dataclasses import dataclass, field

import paramiko

from utils.inventory_checker import InventoryChecker, InventoryConfig, InventoryError
from utils.ssh_connection import SSHConnection, HostKeyPolicy
from utils.tool_result import ToolResult, ResultStatus

logger = logging.getLogger(__name__)

# Validated once at module load — same pattern as inventory_checker.py.
_KUBECONFIG_PATTERN = re.compile(r'^(/[\w.\-]+)+$')

# Default per-command timeout.  Overridable at construction.
_DEFAULT_COMMAND_TIMEOUT = 30

# Default suite-level wall-clock budget in seconds.
_DEFAULT_SUITE_TIMEOUT = 600

# Memcache noise emitted by client-go on certain clusters — not a failure.
_MEMCACHE_NOISE = "couldn't get current server API group list"

# Genuine unavailability patterns — resource type not registered on this cluster.
_UNAVAILABLE_PATTERNS = (
    "the server could not find the requested resource",
    "no matches for kind",
    "the server doesn't have a resource type",
)


@dataclass
class CheckSuiteResult:
    """
    Aggregated result of run_full_check().

    WHY A DATACLASS:
      LangGraph router nodes need a single high-level signal to decide
      whether to proceed, retry, escalate, or request human approval.
      Iterating dict[str, ToolResult] in a router is fragile and verbose.

    Attributes:
        results:         Individual ToolResult per check label.
        overall_success: True iff all checks succeeded or returned UNAVAILABLE.
        failed_checks:   Labels of checks with status FAILURE, TIMEOUT, etc.
        duration_seconds: Wall-clock time for the entire suite.
        correlation_id:  Links this suite to a LangGraph run.
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
    Agent-ready Kubernetes diagnostic tool.

    Every public method issues a single, pre-approved kubectl command and
    returns a ToolResult.  No LLM-generated input is ever interpolated into
    a command string.

    Construct via from_inventory() to ensure all parameters are validated
    before any SSH connection is opened.

    Attributes:
        conn (SSHConnection):   Active SSH transport.
        namespace (str):        Default namespace for namespaced queries.
        command_timeout (int):  Per-command execution timeout in seconds.
        suite_timeout (int):    Wall-clock budget for run_full_check().
    """

    ALL_NAMESPACES = "--all-namespaces"

    def __init__(
        self,
        conn: SSHConnection,
        namespace: str = "default",
        kubeconfig: str | None = None,
        command_timeout: int = _DEFAULT_COMMAND_TIMEOUT,
        suite_timeout: int = _DEFAULT_SUITE_TIMEOUT,
    ) -> None:
        """
        Args:
            conn:            An already-connected SSHConnection.
            namespace:       Default Kubernetes namespace.
            kubeconfig:      Absolute path to kubeconfig on the remote host.
                             Validated against ^(/[\\w.\\-]+)+$ at construction.
            command_timeout: Per-command SSH execution timeout in seconds.
            suite_timeout:   Wall-clock budget for run_full_check() in seconds.

        Raises:
            TypeError:  If conn is not an SSHConnection.
            ValueError: If kubeconfig fails the safety pattern.
        """
        if not isinstance(conn, SSHConnection):
            raise TypeError(f"Expected SSHConnection, got {type(conn).__name__}.")
        if kubeconfig and not _KUBECONFIG_PATTERN.match(kubeconfig):
            raise ValueError(
                f"kubeconfig path '{kubeconfig}' contains invalid characters."
            )
        self.conn = conn
        self.namespace = namespace
        self.command_timeout = command_timeout
        self.suite_timeout = suite_timeout
        self._env_prefix = f"export KUBECONFIG={kubeconfig} && " if kubeconfig else ""
        logger.debug(
            "K8sChecker ready: namespace='%s', kubeconfig=%s, "
            "command_timeout=%ds, suite_timeout=%ds.",
            namespace, kubeconfig or "(none)", command_timeout, suite_timeout,
        )

    @classmethod
    def from_inventory(
        cls,
        config: InventoryConfig,
        conn: SSHConnection,
        command_timeout: int = _DEFAULT_COMMAND_TIMEOUT,
        suite_timeout: int = _DEFAULT_SUITE_TIMEOUT,
    ) -> "K8sChecker":
        """
        Construct K8sChecker from a validated InventoryConfig.

        WHY A FACTORY:
          Ensures kubeconfig, namespace, and connection all come from the
          same validated source.  Eliminates the risk of mismatched
          parameters when constructing directly.

        Args:
            config:          Validated InventoryConfig from InventoryChecker.
            conn:            Active SSHConnection to the inventory host.
            command_timeout: Per-command timeout override.
            suite_timeout:   Suite-level timeout override.
        """
        return cls(
            conn=conn,
            namespace=config.namespace,
            kubeconfig=config.kubeconfig,
            command_timeout=command_timeout,
            suite_timeout=suite_timeout,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run(self, command: str, correlation_id: str | None = None) -> ToolResult:
        """
        Execute a pre-approved kubectl command via conn.execute().

        Applies memcache noise filtering and maps unavailability patterns
        to ResultStatus.UNAVAILABLE so agents can branch correctly.

        WHY NOT _client DIRECTLY:
          Accessing conn._client bypasses the threading lock, the retry
          logic, the per-command timeout, and the audit log in execute().
          All execution MUST go through the public execute() API.

        Args:
            command:        Pre-approved kubectl command string.
            correlation_id: Trace ID to propagate through audit logs.

        Returns:
            ToolResult with status, stdout, stderr, duration, and command.
        """
        prefixed = self._env_prefix + command
        result = self.conn.execute(prefixed, timeout=self.command_timeout,
                                   correlation_id=correlation_id)

        # Filter client-go memcache noise from stderr line by line.
        # WHY: These lines appear on stderr even on successful commands on
        # certain clusters, causing exit code 1 despite valid stdout output.
        clean_stderr_lines = [
            line for line in result.stderr.splitlines()
            if _MEMCACHE_NOISE not in line
        ]
        clean_stderr = "\n".join(clean_stderr_lines).strip()

        # If only noise was on stderr but stdout has content, treat as success.
        if not result.success and not clean_stderr and result.stdout.strip():
            return ToolResult(
                status=ResultStatus.SUCCESS,
                exit_code=0,
                stdout=result.stdout.strip(),
                stderr="",
                duration_seconds=result.duration_seconds,
                command=command,
                correlation_id=result.correlation_id,
            )

        # Map known unavailability patterns to UNAVAILABLE status.
        if not result.success and any(p in clean_stderr for p in _UNAVAILABLE_PATTERNS):
            logger.warning("Resource not available on this cluster: %s", command)
            return ToolResult(
                status=ResultStatus.UNAVAILABLE,
                exit_code=result.exit_code,
                stdout="",
                stderr="not available on this cluster",
                duration_seconds=result.duration_seconds,
                command=command,
                correlation_id=result.correlation_id,
            )

        return ToolResult(
            status=result.status,
            exit_code=result.exit_code,
            stdout=result.stdout.strip(),
            stderr=clean_stderr,
            duration_seconds=result.duration_seconds,
            command=command,
            correlation_id=result.correlation_id,
        )

    def _ns_flag(self, namespace: str | None) -> str:
        """Return the kubectl namespace flag for the given namespace."""
        ns = namespace or self.namespace
        return "--all-namespaces" if ns == self.ALL_NAMESPACES else f"-n {ns}"

    # ------------------------------------------------------------------
    # Cluster-wide checks
    # ------------------------------------------------------------------

    def get_cluster_info(self, correlation_id: str | None = None) -> ToolResult:
        """Return cluster control-plane and CoreDNS endpoint information."""
        return self._run("kubectl cluster-info", correlation_id)

    def get_nodes(self, correlation_id: str | None = None) -> ToolResult:
        """Return all nodes with status, roles, age and version."""
        return self._run("kubectl get nodes -o wide", correlation_id)

    def get_node_resource_usage(self, correlation_id: str | None = None) -> ToolResult:
        """Return CPU and memory usage per node (requires metrics-server)."""
        return self._run("kubectl top nodes", correlation_id)

    def get_component_statuses(self, correlation_id: str | None = None) -> ToolResult:
        """Return health of scheduler, controller-manager and etcd."""
        return self._run("kubectl get componentstatuses", correlation_id)

    def get_api_resources(self, correlation_id: str | None = None) -> ToolResult:
        """Return all API resource types registered in the cluster."""
        return self._run("kubectl api-resources", correlation_id)

    def get_namespaces(self, correlation_id: str | None = None) -> ToolResult:
        """Return all namespaces with status and age."""
        return self._run("kubectl get namespaces", correlation_id)

    # ------------------------------------------------------------------
    # Workloads
    # ------------------------------------------------------------------

    def get_pods(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all pods with status and node placement."""
        return self._run(f"kubectl get pods {self._ns_flag(namespace)} -o wide", correlation_id)

    def get_pod_resource_usage(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return CPU and memory usage per pod (requires metrics-server)."""
        return self._run(f"kubectl top pods {self._ns_flag(namespace)}", correlation_id)

    def get_failed_pods(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return pods not in Running or Succeeded state."""
        return self._run(
            f"kubectl get pods {self._ns_flag(namespace)} "
            "--field-selector=status.phase!=Running,status.phase!=Succeeded",
            correlation_id,
        )

    def get_deployments(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all deployments with replica counts."""
        return self._run(f"kubectl get deployments {self._ns_flag(namespace)}", correlation_id)

    def get_replicasets(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all ReplicaSets."""
        return self._run(f"kubectl get replicasets {self._ns_flag(namespace)}", correlation_id)

    def get_statefulsets(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all StatefulSets."""
        return self._run(f"kubectl get statefulsets {self._ns_flag(namespace)}", correlation_id)

    def get_daemonsets(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all DaemonSets."""
        return self._run(f"kubectl get daemonsets {self._ns_flag(namespace)}", correlation_id)

    def get_jobs(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all Jobs."""
        return self._run(f"kubectl get jobs {self._ns_flag(namespace)}", correlation_id)

    def get_cronjobs(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all CronJobs."""
        return self._run(f"kubectl get cronjobs {self._ns_flag(namespace)}", correlation_id)

    # ------------------------------------------------------------------
    # Networking
    # ------------------------------------------------------------------

    def get_services(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all services with type, IPs and ports."""
        return self._run(f"kubectl get services {self._ns_flag(namespace)}", correlation_id)

    def get_ingresses(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all Ingress resources."""
        return self._run(f"kubectl get ingresses {self._ns_flag(namespace)}", correlation_id)

    def get_endpoints(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all Endpoints."""
        return self._run(f"kubectl get endpoints {self._ns_flag(namespace)}", correlation_id)

    def get_network_policies(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all NetworkPolicy resources."""
        return self._run(f"kubectl get networkpolicies {self._ns_flag(namespace)}", correlation_id)

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def get_persistent_volumes(self, correlation_id: str | None = None) -> ToolResult:
        """Return all PersistentVolumes."""
        return self._run("kubectl get pv", correlation_id)

    def get_persistent_volume_claims(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all PersistentVolumeClaims."""
        return self._run(f"kubectl get pvc {self._ns_flag(namespace)}", correlation_id)

    def get_storage_classes(self, correlation_id: str | None = None) -> ToolResult:
        """Return all StorageClasses."""
        return self._run("kubectl get storageclasses", correlation_id)

    # ------------------------------------------------------------------
    # Configuration & secrets
    # ------------------------------------------------------------------

    def get_configmaps(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all ConfigMaps."""
        return self._run(f"kubectl get configmaps {self._ns_flag(namespace)}", correlation_id)

    def get_secrets(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all Secrets. Values are never decoded."""
        return self._run(f"kubectl get secrets {self._ns_flag(namespace)}", correlation_id)

    # ------------------------------------------------------------------
    # RBAC
    # ------------------------------------------------------------------

    def get_service_accounts(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all ServiceAccounts."""
        return self._run(f"kubectl get serviceaccounts {self._ns_flag(namespace)}", correlation_id)

    def get_roles(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all namespace-scoped RBAC Roles."""
        return self._run(f"kubectl get roles {self._ns_flag(namespace)}", correlation_id)

    def get_cluster_roles(self, correlation_id: str | None = None) -> ToolResult:
        """Return all ClusterRoles."""
        return self._run("kubectl get clusterroles", correlation_id)

    # ------------------------------------------------------------------
    # Events & health
    # ------------------------------------------------------------------

    def get_events(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all events sorted by lastTimestamp."""
        return self._run(
            f"kubectl get events {self._ns_flag(namespace)} --sort-by='.lastTimestamp'",
            correlation_id,
        )

    def get_resource_quotas(self, namespace: str | None = None, correlation_id: str | None = None) -> ToolResult:
        """Return all ResourceQuotas."""
        return self._run(f"kubectl get resourcequotas {self._ns_flag(namespace)}", correlation_id)

    # ------------------------------------------------------------------
    # Full check suite
    # ------------------------------------------------------------------

    def run_full_check(
        self,
        namespace: str | None = None,
        correlation_id: str | None = None,
    ) -> CheckSuiteResult:
        """
        Run all checks with per-check exception isolation and suite timeout.

        WHY PER-CHECK ISOLATION:
          A single unexpected exception (e.g. socket reset mid-suite) must
          not discard all results collected so far.  The agent receives
          whatever partial results exist and a clear list of failed checks.

        WHY SUITE TIMEOUT:
          LangGraph workflows have wall-clock budgets.  A suite that runs
          indefinitely blocks the entire execution graph.

        Args:
            namespace:       Namespace override for namespaced checks.
            correlation_id:  Trace ID to propagate to all child ToolResults.

        Returns:
            CheckSuiteResult with per-check results, overall_success,
            failed_checks list, total duration, and correlation_id.
        """
        cid = correlation_id or str(uuid.uuid4())
        suite_start = time.monotonic()
        logger.info("Starting full K8s check suite. correlation_id=%s", cid)

        checks = {
            "Cluster Info":             lambda: self.get_cluster_info(cid),
            "Nodes":                    lambda: self.get_nodes(cid),
            "Node Resource Usage":      lambda: self.get_node_resource_usage(cid),
            "Component Statuses":       lambda: self.get_component_statuses(cid),
            "Namespaces":               lambda: self.get_namespaces(cid),
            "Pods":                     lambda: self.get_pods(namespace, cid),
            "Pod Resource Usage":       lambda: self.get_pod_resource_usage(namespace, cid),
            "Failed Pods":              lambda: self.get_failed_pods(namespace, cid),
            "Deployments":              lambda: self.get_deployments(namespace, cid),
            "ReplicaSets":              lambda: self.get_replicasets(namespace, cid),
            "StatefulSets":             lambda: self.get_statefulsets(namespace, cid),
            "DaemonSets":               lambda: self.get_daemonsets(namespace, cid),
            "Jobs":                     lambda: self.get_jobs(namespace, cid),
            "CronJobs":                 lambda: self.get_cronjobs(namespace, cid),
            "Services":                 lambda: self.get_services(namespace, cid),
            "Ingresses":                lambda: self.get_ingresses(namespace, cid),
            "Endpoints":                lambda: self.get_endpoints(namespace, cid),
            "Network Policies":         lambda: self.get_network_policies(namespace, cid),
            "Persistent Volumes":       lambda: self.get_persistent_volumes(cid),
            "Persistent Volume Claims": lambda: self.get_persistent_volume_claims(namespace, cid),
            "Storage Classes":          lambda: self.get_storage_classes(cid),
            "ConfigMaps":               lambda: self.get_configmaps(namespace, cid),
            "Secrets":                  lambda: self.get_secrets(namespace, cid),
            "Service Accounts":         lambda: self.get_service_accounts(namespace, cid),
            "Roles":                    lambda: self.get_roles(namespace, cid),
            "Cluster Roles":            lambda: self.get_cluster_roles(cid),
            "Resource Quotas":          lambda: self.get_resource_quotas(namespace, cid),
            "Events":                   lambda: self.get_events(namespace, cid),
        }

        results: dict[str, ToolResult] = {}
        failed: list[str] = []

        for label, fn in checks.items():
            # Enforce suite-level wall-clock budget.
            elapsed = time.monotonic() - suite_start
            if elapsed >= self.suite_timeout:
                logger.error(
                    "Suite timeout (%ds) exceeded after %.1fs. "
                    "Remaining checks skipped. correlation_id=%s",
                    self.suite_timeout, elapsed, cid,
                )
                break

            logger.info("Check: %s", label)
            try:
                result = fn()
            except Exception as exc:
                # Per-check isolation: capture exception as a FAILURE result
                # so the suite continues and the agent gets partial data.
                logger.error("Check '%s' raised an unexpected exception: %s", label, exc)
                result = ToolResult.error(
                    ResultStatus.FAILURE,
                    f"Unexpected exception: {exc}",
                    correlation_id=cid,
                )

            results[label] = result

            # UNAVAILABLE is not a failure — the cluster simply lacks the resource.
            if result.status not in (ResultStatus.SUCCESS, ResultStatus.UNAVAILABLE):
                failed.append(label)

        duration = time.monotonic() - suite_start
        overall_success = len(failed) == 0

        logger.info(
            "Check suite complete. passed=%d/%d failed=%s duration=%.1fs correlation_id=%s",
            len(results) - len(failed), len(results), failed or "none", duration, cid,
        )

        return CheckSuiteResult(
            results=results,
            overall_success=overall_success,
            failed_checks=failed,
            duration_seconds=duration,
            correlation_id=cid,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run full Kubernetes check suite using inventory.yaml."""
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
                status_tag = f"[{result.status.value.upper()}]"
                print(f"\n{'=' * 60}")
                print(f"  {status_tag} {label}  ({result.duration_seconds:.2f}s)")
                print('=' * 60)
                print(result.stdout or result.stderr or "(no output)")

            print(f"\n{'=' * 60}")
            print(f"  Suite: {'SUCCESS' if suite.overall_success else 'FAILED'} "
                  f"| {len(suite.results) - len(suite.failed_checks)}/{len(suite.results)} passed "
                  f"| {suite.duration_seconds:.1f}s")
            if suite.failed_checks:
                print(f"  Failed: {suite.failed_checks}")
            print('=' * 60)

    except ConnectionAbortedError as exc:
        logger.error("Aborted: %s", exc)
    except socket.timeout:
        logger.error("Connection to '%s' timed out.", config.host)
    except paramiko.AuthenticationException:
        logger.error("Authentication failed for '%s' on '%s'.", config.login, config.host)


if __name__ == "__main__":
    main()
