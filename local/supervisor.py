# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Local harness supervisor — runs every ARIA process in one place.

Plays the role a docker-compose file would, but as a Python supervisor so all
child logs stream into one tagged, followable output (Lumina found compose hid
agent logs). It:

  1. Starts moto (DynamoDB + S3 + Secrets Manager emulators) on one port.
  2. Waits for moto, then provisions tables/bucket/secret (init_aws.py).
  3. Starts the AgentCore shim (runtime + memory), the MCP gateway shim, and the
     browser-facing agent proxy shim.
  4. Starts the seven agent processes (run_agent.py per AGENT_NAME).
  5. Starts the backend (uvicorn main:app).
  6. Optionally seeds local ERPNext (ARIA_SEED_ON_START=true).

Every child inherits the endpoint + app env from local/config/harness_env.py, so
the unmodified application wires itself to local infra. Bedrock stays real.

ERPNext itself runs via infra/docker/docker-compose.local-test.yaml (started
separately by the Makefile), and the frontend runs via `npm run dev` (also the
Makefile) — both are long-lived and external to this supervisor.

Usage:
    python local/supervisor.py
"""

from __future__ import annotations

import logging
import os
import signal
# Child argv is always built from repo paths + sys.executable (no shell, no
# external input), so the subprocess usages below are safe.
import subprocess  # nosec B404
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "config"))
import harness_env as H  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s supervisor %(message)s")
logger = logging.getLogger("supervisor")

REPO = Path(__file__).resolve().parent.parent
LOCAL = REPO / "local"
BACKEND = REPO / "backend"
PY = sys.executable


class Supervisor:
    def __init__(self) -> None:
        self._procs: list[tuple[str, subprocess.Popen]] = []
        self._stop = threading.Event()

    def spawn(self, name: str, argv: list[str], *, cwd: Path | None = None,
              extra_env: dict[str, str] | None = None) -> None:
        env = dict(os.environ)
        env.update(H.app_env())
        if extra_env:
            env.update(extra_env)
        proc = subprocess.Popen(  # nosec B603  # nosemgrep: dangerous-subprocess-use-audit
            argv,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._procs.append((name, proc))
        threading.Thread(target=self._pump, args=(name, proc), daemon=True).start()
        logger.info("started %s (pid %d)", name, proc.pid)

    def _pump(self, name: str, proc: subprocess.Popen) -> None:
        if proc.stdout is None:
            return
        for line in proc.stdout:
            sys.stdout.write(f"[{name}] {line}")
            sys.stdout.flush()

    def watch(self) -> None:
        while not self._stop.is_set():
            for name, proc in self._procs:
                if proc.poll() is not None:
                    logger.error("%s exited (code %s) — shutting down", name, proc.returncode)
                    self.shutdown()
                    return
            time.sleep(1.0)  # nosemgrep: arbitrary-sleep -- fixed process-watch poll interval

    def shutdown(self) -> None:
        self._stop.set()
        for name, proc in reversed(self._procs):
            if proc.poll() is None:
                logger.info("stopping %s", name)
                proc.terminate()
        deadline = time.monotonic() + 10.0
        for _name, proc in reversed(self._procs):
            if proc.poll() is None:
                try:
                    proc.wait(timeout=max(0.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    proc.kill()


def _wait_for_moto(timeout: float = 30.0) -> None:
    import urllib.request

    url = f"http://127.0.0.1:{H.MOTO_PORT}/moto-api/"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            # Fixed localhost readiness probe — not user/dynamic input.
            urllib.request.urlopen(url, timeout=2)  # nosec B310  # nosemgrep: dynamic-urllib-use-detected
            logger.info("moto ready on :%d", H.MOTO_PORT)
            return
        except Exception:
            time.sleep(0.5)  # nosemgrep: arbitrary-sleep -- readiness backoff between probes
    raise SystemExit("moto did not become ready in time")


def main() -> int:
    sup = Supervisor()

    def _sig(_signum, _frame):
        logger.info("signal received, shutting down")
        sup.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    # 1) Emulators (moto: dynamodb + s3 + secretsmanager on one port).
    sup.spawn("moto", [PY, "-m", "moto.server", "-p", str(H.MOTO_PORT)])
    _wait_for_moto()

    # 2) Provision tables/bucket/secret.
    rc = subprocess.run(  # nosec B603  # nosemgrep: dangerous-subprocess-use-audit
        [PY, str(LOCAL / "scripts" / "init_aws.py")],
        env={**os.environ, **H.app_env()},
    ).returncode
    if rc != 0:
        logger.error("init_aws failed (rc=%d)", rc)
        sup.shutdown()
        return rc

    # 3) Shims.
    sup.spawn("agentcore-shim", [PY, str(LOCAL / "shims" / "agentcore_shim.py")])
    sup.spawn("mcp-gateway", [PY, str(LOCAL / "shims" / "mcp_gateway_shim.py")])
    sup.spawn("agent-proxy", [PY, str(LOCAL / "shims" / "agent_proxy_shim.py")])
    # Canonical ERP REST API for the SPA's /api/erp/* calls.
    sup.spawn(
        "canonical-api",
        [PY, "-m", "uvicorn", "canonical_api_shim:app", "--host", "127.0.0.1",
         "--port", str(H.CANONICAL_API_PORT)],
        cwd=LOCAL / "shims",
    )

    # 4) Agents (one process per kind, backend/agentcore_app.py via run_agent.py).
    for kind, port in H.AGENT_PORTS.items():
        sup.spawn(f"agent:{kind}", [PY, str(LOCAL / "shims" / "run_agent.py"), kind, str(port)])

    # 5) Backend (operational routes: chat, dashboard, config, decisions, invoices).
    sup.spawn(
        "backend",
        [PY, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(H.BACKEND_PORT)],
        cwd=BACKEND,
    )

    # 6) Optional seed.
    if os.environ.get("ARIA_SEED_ON_START", "false").lower() == "true":
        logger.info("ARIA_SEED_ON_START=true — seeding local ERPNext")
        subprocess.run(  # nosec B603  # nosemgrep: dangerous-subprocess-use-audit
            [PY, str(LOCAL / "scripts" / "seed_local.py")],
            env={**os.environ, **H.app_env()},
        )

    logger.info("all processes started — backend on :%d", H.BACKEND_PORT)
    logger.info("start the SPA separately with: make -C local ui   (Vite on :5173)")
    sup.watch()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
