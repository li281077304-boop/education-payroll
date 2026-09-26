"""Environment normalisation shared by the whole suite.

Two ambient conditions used to make this suite fail for reasons that had
nothing to do with the code under test:

* a shell/sandbox that exports ``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``ALL_PROXY``
  pointed at a local proxy.  Tests that talk to loopback ports (the launcher
  health probe, the in-process HTTP server fixtures) had their loopback request
  answered by that proxy and read the answer as "a foreign program owns this
  port";
* a launcher that injects its own shim through ``PYTHONPATH``, which intercepts
  ``mkdir`` and turns pytest's ``tmp_path`` setup into ``PermissionError``.

The suite owns its own environment: loopback traffic is always direct, and
proxy variables are removed for the duration of the run.  Tests must not
depend on whatever the developer's shell happened to export.
"""
from __future__ import annotations

import os

_PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "FTP_PROXY",
    "ftp_proxy",
)

_LOCAL_HOSTS = "localhost,127.0.0.1,::1,0.0.0.0"


def normalise_environment() -> dict[str, str]:
    """Force direct loopback traffic and report the variables that were cleared."""
    removed: dict[str, str] = {}
    for name in _PROXY_VARIABLES:
        value = os.environ.pop(name, None)
        if value is not None:
            removed[name] = value
    os.environ["NO_PROXY"] = _LOCAL_HOSTS
    os.environ["no_proxy"] = _LOCAL_HOSTS
    return removed


normalise_environment()
