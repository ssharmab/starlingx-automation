# SPDX-License-Identifier: Apache-2.0
"""
bmc_target.py
-------------
Typed input contract for a single BMC target.

Why this exists:
- Decouples VmcObject from any config source (file, Secrets Manager, agent
  state, SSM, etc.).  The caller is responsible for obtaining credentials;
  rvmc internals never touch the filesystem or environment directly.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field


@dataclass
class BmcTarget:
    """
    All information required to connect to and provision a single BMC.

    Attributes:
        address:     BMC IP address (IPv4 or IPv6, without brackets).
        username:    BMC login username.
        password:    Plaintext BMC password (decoded by the caller).
        image:       Full HTTP/HTTPS URL of the ISO image to inject.
        target_name: Optional human-readable label used in logs.
        debug:       Debug verbosity level 0-4 (default 0 = off).
    """
    address: str
    username: str
    password: str
    image: str
    target_name: str | None = None
    debug: int = 0

    @classmethod
    def from_config(cls, target_name: str | None, cfg: dict, debug: int = 0) -> "BmcTarget":
        """
        Build a BmcTarget from a raw config dictionary.

        Accepts the same dict shape used by the legacy rvmc.yaml so the CLI
        shim can keep reading files without changing this class.

        :param target_name: arbitrary label for this target
        :param cfg: dict with keys bmc_address, bmc_username, bmc_password
                    (base64), image
        :param debug: debug level
        :raises ValueError: if any required key is missing or password cannot
                            be decoded
        """
        pw_encoded = cfg.get('bmc_password')
        if pw_encoded is None:
            raise ValueError("Missing 'bmc_password' in config")
        try:
            password = base64.b64decode(pw_encoded).decode('utf-8')
        except Exception as ex:
            raise ValueError("Failed to decode bmc_password: %s" % ex)

        address = cfg.get('bmc_address')
        if address is None:
            raise ValueError("Missing 'bmc_address' in config")

        image = cfg.get('image')
        if image is None:
            raise ValueError("Missing 'image' in config")

        username = cfg.get('bmc_username')
        if username is None:
            raise ValueError("Missing 'bmc_username' in config")

        return cls(
            address=address.strip(),
            username=username.strip(),
            password=password,
            image=image.strip(),
            target_name=target_name,
            debug=debug,
        )
