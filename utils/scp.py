# SPDX-License-Identifier: Apache-2.0
"""
scp.py
------
SCP file transfer utility built on top of SSHConnection.

LAYER: Transport
  This module handles file transfers over SSH using SFTP (Paramiko's
  SFTP subsystem). It has no knowledge of agents, tools, or workflows.

Why this exists:

- Provides a reusable, structured file transfer capability.
- Supports upload (local → remote) and download (remote → local).
- Thread-safe — reuses the SSHConnection lock.
- Returns structured results for agent consumption.
"""

from __future__ import annotations

import logging
import os
import stat
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import paramiko

from utils.ssh_connection import SSHConnection, HostKeyPolicy

logger = logging.getLogger(__name__)


class TransferDirection(str, Enum):
    """Direction of the file transfer."""
    UPLOAD = "upload"      # local → remote
    DOWNLOAD = "download"  # remote → local


@dataclass
class TransferResult:
    """Structured result of a file transfer operation."""
    success: bool
    direction: TransferDirection
    source: str
    destination: str
    bytes_transferred: int = 0
    duration_seconds: float = 0.0
    error: str = ""

    def __str__(self) -> str:
        status = "OK" if self.success else "FAILED"
        return (
            f"[{status}] {self.direction.value}: "
            f"{self.source} → {self.destination} "
            f"({self.bytes_transferred} bytes in {self.duration_seconds:.2f}s)"
        )


class SCPTransfer:
    """
    File transfer over SSH using Paramiko's SFTP subsystem.

    Supports:
    - Single file upload (local → remote)
    - Single file download (remote → local)
    - Directory upload (recursive)
    - Directory download (recursive)

    Usage:
        scp = SCPTransfer(host="10.0.0.1", login="admin", password="pass")
        scp.connect()
        result = scp.upload("/local/file.txt", "/remote/file.txt")
        scp.disconnect()

    Or as a context manager:
        with SCPTransfer(host="10.0.0.1", login="admin", password="pass") as scp:
            result = scp.upload("/local/file.txt", "/remote/file.txt")
    """

    def __init__(
        self,
        host: str,
        login: str,
        password: str,
        port: int = 22,
        host_key_policy: HostKeyPolicy = HostKeyPolicy.TRUST_ON_FIRST_USE,
        connect_timeout: int = 10,
    ) -> None:
        self._ssh = SSHConnection(
            host=host,
            login=login,
            password=password,
            port=port,
            host_key_policy=host_key_policy,
            connect_timeout=connect_timeout,
        )
        self._sftp: paramiko.SFTPClient | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Establish SSH connection and open SFTP channel."""
        self._ssh.connect()
        transport = self._ssh._client.get_transport()
        if transport is None:
            raise ConnectionError("SSH transport is not available.")
        self._sftp = paramiko.SFTPClient.from_transport(transport)
        logger.info("SFTP channel opened to %s.", self._ssh.host)

    def disconnect(self) -> None:
        """Close SFTP channel and SSH connection."""
        if self._sftp:
            self._sftp.close()
            self._sftp = None
        self._ssh.disconnect()
        logger.info("SFTP channel closed.")

    @property
    def is_connected(self) -> bool:
        """True if both SSH and SFTP are active."""
        return self._ssh.is_connected and self._sftp is not None

    # ------------------------------------------------------------------
    # File transfers
    # ------------------------------------------------------------------

    def upload(self, local_path: str, remote_path: str) -> TransferResult:
        """
        Upload a file or directory from local to remote.

        Args:
            local_path:  Path to the local file or directory.
            remote_path: Destination path on the remote host.

        Returns:
            TransferResult with success status and transfer details.
        """
        if not self.is_connected:
            return TransferResult(
                success=False,
                direction=TransferDirection.UPLOAD,
                source=local_path,
                destination=remote_path,
                error="Not connected. Call connect() first.",
            )

        local = Path(local_path)

        if not local.exists():
            return TransferResult(
                success=False,
                direction=TransferDirection.UPLOAD,
                source=local_path,
                destination=remote_path,
                error=f"Local path does not exist: {local_path}",
            )

        if local.is_dir():
            return self._upload_directory(local_path, remote_path)

        return self._upload_file(local_path, remote_path)

    def download(self, remote_path: str, local_path: str) -> TransferResult:
        """
        Download a file or directory from remote to local.

        Args:
            remote_path: Path to the remote file or directory.
            local_path:  Destination path on the local machine.

        Returns:
            TransferResult with success status and transfer details.
        """
        if not self.is_connected:
            return TransferResult(
                success=False,
                direction=TransferDirection.DOWNLOAD,
                source=remote_path,
                destination=local_path,
                error="Not connected. Call connect() first.",
            )

        # Check if remote path is a directory
        try:
            remote_stat = self._sftp.stat(remote_path)
            if stat.S_ISDIR(remote_stat.st_mode):
                return self._download_directory(remote_path, local_path)
        except FileNotFoundError:
            return TransferResult(
                success=False,
                direction=TransferDirection.DOWNLOAD,
                source=remote_path,
                destination=local_path,
                error=f"Remote path does not exist: {remote_path}",
            )
        except IOError as exc:
            return TransferResult(
                success=False,
                direction=TransferDirection.DOWNLOAD,
                source=remote_path,
                destination=local_path,
                error=f"Cannot stat remote path: {exc}",
            )

        return self._download_file(remote_path, local_path)

    # ------------------------------------------------------------------
    # Internal: single file operations
    # ------------------------------------------------------------------

    def _upload_file(self, local_path: str, remote_path: str) -> TransferResult:
        """Upload a single file."""
        start = time.monotonic()
        try:
            file_info = self._sftp.put(local_path, remote_path)
            duration = time.monotonic() - start
            bytes_transferred = file_info.st_size if file_info else os.path.getsize(local_path)

            logger.info("Uploaded %s → %s (%d bytes)", local_path, remote_path, bytes_transferred)
            return TransferResult(
                success=True,
                direction=TransferDirection.UPLOAD,
                source=local_path,
                destination=remote_path,
                bytes_transferred=bytes_transferred,
                duration_seconds=duration,
            )
        except FileNotFoundError as exc:
            return TransferResult(
                success=False,
                direction=TransferDirection.UPLOAD,
                source=local_path,
                destination=remote_path,
                duration_seconds=time.monotonic() - start,
                error=f"File not found: {exc}",
            )
        except PermissionError as exc:
            return TransferResult(
                success=False,
                direction=TransferDirection.UPLOAD,
                source=local_path,
                destination=remote_path,
                duration_seconds=time.monotonic() - start,
                error=f"Permission denied: {exc}",
            )
        except IOError as exc:
            return TransferResult(
                success=False,
                direction=TransferDirection.UPLOAD,
                source=local_path,
                destination=remote_path,
                duration_seconds=time.monotonic() - start,
                error=f"Transfer failed: {exc}",
            )

    def _download_file(self, remote_path: str, local_path: str) -> TransferResult:
        """Download a single file."""
        start = time.monotonic()

        # Ensure local directory exists
        local_dir = os.path.dirname(local_path)
        if local_dir:
            os.makedirs(local_dir, exist_ok=True)

        try:
            self._sftp.get(remote_path, local_path)
            duration = time.monotonic() - start
            bytes_transferred = os.path.getsize(local_path)

            logger.info("Downloaded %s → %s (%d bytes)", remote_path, local_path, bytes_transferred)
            return TransferResult(
                success=True,
                direction=TransferDirection.DOWNLOAD,
                source=remote_path,
                destination=local_path,
                bytes_transferred=bytes_transferred,
                duration_seconds=duration,
            )
        except FileNotFoundError as exc:
            return TransferResult(
                success=False,
                direction=TransferDirection.DOWNLOAD,
                source=remote_path,
                destination=local_path,
                duration_seconds=time.monotonic() - start,
                error=f"Remote file not found: {exc}",
            )
        except PermissionError as exc:
            return TransferResult(
                success=False,
                direction=TransferDirection.DOWNLOAD,
                source=remote_path,
                destination=local_path,
                duration_seconds=time.monotonic() - start,
                error=f"Permission denied: {exc}",
            )
        except IOError as exc:
            return TransferResult(
                success=False,
                direction=TransferDirection.DOWNLOAD,
                source=remote_path,
                destination=local_path,
                duration_seconds=time.monotonic() - start,
                error=f"Transfer failed: {exc}",
            )

    # ------------------------------------------------------------------
    # Internal: directory operations (recursive)
    # ------------------------------------------------------------------

    def _mkdir_remote(self, remote_dir: str) -> None:
        """Create remote directory, ignoring if it already exists."""
        try:
            self._sftp.stat(remote_dir)
        except FileNotFoundError:
            self._sftp.mkdir(remote_dir)

    def _upload_directory(self, local_path: str, remote_path: str) -> TransferResult:
        """Recursively upload a directory."""
        start = time.monotonic()
        total_bytes = 0

        try:
            self._mkdir_remote(remote_path)

            for root, dirs, files in os.walk(local_path):
                # Calculate relative path from the source directory
                rel_root = os.path.relpath(root, local_path)
                if rel_root == ".":
                    current_remote = remote_path
                else:
                    current_remote = remote_path + "/" + rel_root.replace("\\", "/")

                # Create subdirectories on remote
                for d in dirs:
                    self._mkdir_remote(current_remote + "/" + d)

                # Upload files
                for f in files:
                    local_file = os.path.join(root, f)
                    remote_file = current_remote + "/" + f
                    file_info = self._sftp.put(local_file, remote_file)
                    total_bytes += file_info.st_size if file_info else os.path.getsize(local_file)

            duration = time.monotonic() - start
            logger.info("Uploaded directory %s → %s (%d bytes)", local_path, remote_path, total_bytes)
            return TransferResult(
                success=True,
                direction=TransferDirection.UPLOAD,
                source=local_path,
                destination=remote_path,
                bytes_transferred=total_bytes,
                duration_seconds=duration,
            )
        except Exception as exc:
            return TransferResult(
                success=False,
                direction=TransferDirection.UPLOAD,
                source=local_path,
                destination=remote_path,
                bytes_transferred=total_bytes,
                duration_seconds=time.monotonic() - start,
                error=f"Directory upload failed: {exc}",
            )

    def _download_directory(self, remote_path: str, local_path: str) -> TransferResult:
        """Recursively download a directory."""
        start = time.monotonic()
        total_bytes = 0

        try:
            os.makedirs(local_path, exist_ok=True)

            self._download_dir_recursive(remote_path, local_path, total_bytes_ref=[0])
            total_bytes = self._last_download_bytes

            duration = time.monotonic() - start
            logger.info("Downloaded directory %s → %s (%d bytes)", remote_path, local_path, total_bytes)
            return TransferResult(
                success=True,
                direction=TransferDirection.DOWNLOAD,
                source=remote_path,
                destination=local_path,
                bytes_transferred=total_bytes,
                duration_seconds=duration,
            )
        except Exception as exc:
            return TransferResult(
                success=False,
                direction=TransferDirection.DOWNLOAD,
                source=remote_path,
                destination=local_path,
                bytes_transferred=total_bytes,
                duration_seconds=time.monotonic() - start,
                error=f"Directory download failed: {exc}",
            )

    def _download_dir_recursive(self, remote_path: str, local_path: str, total_bytes_ref: list) -> None:
        """Helper for recursive directory download."""
        os.makedirs(local_path, exist_ok=True)

        for entry in self._sftp.listdir_attr(remote_path):
            remote_entry = remote_path + "/" + entry.filename
            local_entry = os.path.join(local_path, entry.filename)

            if stat.S_ISDIR(entry.st_mode):
                self._download_dir_recursive(remote_entry, local_entry, total_bytes_ref)
            else:
                self._sftp.get(remote_entry, local_entry)
                total_bytes_ref[0] += os.path.getsize(local_entry)

        self._last_download_bytes = total_bytes_ref[0]

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "SCPTransfer":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.disconnect()
        return False


# ---------------------------------------------------------------------------
# __main__ test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import tempfile
    from pathlib import Path as _Path

    sys.path.insert(0, str(_Path(__file__).parent.parent))

    print("=" * 60)
    print("  SCPTransfer — test harness")
    print("=" * 60)

    # Load inventory for a real host test
    inventory_path = os.path.join(
        os.path.dirname(__file__), "..", "inventory", "inventory.yaml"
    )

    try:
        import yaml
        with open(inventory_path) as f:
            inv = yaml.safe_load(f)
        host = inv["host"]
        login = inv["login"]
        password = inv["password"]
    except Exception as exc:
        print(f"\n  Cannot load inventory ({exc}). Skipping live tests.")
        print("  Create inventory/inventory.yaml with host, login, password.")
        sys.exit(0)

    # --- Test 1: Upload a file ---
    print("\n--- Test 1: Upload a temporary file ---")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("Hello from SCP transfer test!\n")
        tmp_local = tmp.name

    remote_dest = "/tmp/scp_test_upload.txt"

    try:
        with SCPTransfer(host=host, login=login, password=password) as scp:
            result = scp.upload(tmp_local, remote_dest)
            print(f"  {result}")
            assert result.success, f"Upload failed: {result.error}"
            assert result.bytes_transferred > 0
            print("  PASS")
    except Exception as exc:
        print(f"  FAIL: {exc}")
    finally:
        os.unlink(tmp_local)

    # --- Test 2: Download the file back ---
    print("\n--- Test 2: Download the file back ---")
    local_download = tempfile.mktemp(suffix=".txt")

    try:
        with SCPTransfer(host=host, login=login, password=password) as scp:
            result = scp.download(remote_dest, local_download)
            print(f"  {result}")
            assert result.success, f"Download failed: {result.error}"
            assert result.bytes_transferred > 0

            with open(local_download) as f:
                content = f.read()
            assert "Hello from SCP" in content
            print(f"  Content: {content.strip()}")
            print("  PASS")
    except Exception as exc:
        print(f"  FAIL: {exc}")
    finally:
        if os.path.exists(local_download):
            os.unlink(local_download)

    # --- Test 3: Upload non-existent file ---
    print("\n--- Test 3: Upload non-existent file ---")
    try:
        with SCPTransfer(host=host, login=login, password=password) as scp:
            result = scp.upload("/no/such/file.txt", "/tmp/nope.txt")
            print(f"  success: {result.success}")
            print(f"  error  : {result.error}")
            assert result.success is False
            print("  PASS")
    except Exception as exc:
        print(f"  FAIL: {exc}")

    # --- Test 4: Download non-existent remote file ---
    print("\n--- Test 4: Download non-existent remote file ---")
    try:
        with SCPTransfer(host=host, login=login, password=password) as scp:
            result = scp.download("/no/such/remote/file.txt", "/tmp/nope.txt")
            print(f"  success: {result.success}")
            print(f"  error  : {result.error}")
            assert result.success is False
            print("  PASS")
    except Exception as exc:
        print(f"  FAIL: {exc}")

    # --- Test 5: Not connected ---
    print("\n--- Test 5: Transfer without connect ---")
    scp = SCPTransfer(host=host, login=login, password=password)
    result = scp.upload("/tmp/anything", "/tmp/anywhere")
    print(f"  success: {result.success}")
    print(f"  error  : {result.error}")
    assert result.success is False
    assert "Not connected" in result.error
    print("  PASS")

    print("\n" + "=" * 60)
    print("  All SCPTransfer tests complete.")
    print("=" * 60)
