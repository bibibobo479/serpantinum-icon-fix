"""Explicit restart of one daemon-managed Serpantinum instance."""

import os
from pathlib import Path
import shutil
import subprocess
import time

from .core import RepairError, running_shells


def restart_shell(ctx, shell):
    active = running_shells()
    if len(active) != 1 or active[0][1] != shell:
        raise RepairError("Restart requires exactly one running instance of the selected Serpantinum installation.")
    pid, _, entrypoint = active[0]
    daemon = shell.parent.parent / "bin/serpantinumd"
    if not daemon.is_file():
        located = shutil.which("serpantinumd")
        if not located:
            raise RepairError("serpantinumd is unavailable; restart using your session manager.")
        daemon = Path(located)
    env = dict(item.decode().split("=", 1) for item in
               Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if item)
    env["MAIN_QML"] = str(entrypoint)
    env["SERPANTINUM_DIR"] = str(shell.parent)
    status = subprocess.run([str(daemon), "status"], env=env, capture_output=True, timeout=10)
    if status.returncode:
        raise RepairError("This instance is not managed by serpantinumd; restart it with your session manager.")
    ctx.state.mkdir(parents=True, exist_ok=True)
    log = ctx.state / "restart.log"
    with log.open("ab") as out:
        subprocess.run([str(daemon), "stop"], env=env, stdout=out, stderr=out, check=True, timeout=20)
        proc = subprocess.Popen([str(daemon), "start"], env=env, cwd=ctx.home,
                                stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                start_new_session=True)
    for _ in range(30):
        time.sleep(0.2)
        if proc.poll() is not None:
            raise RepairError(f"Serpantinum exited during restart. Inspect {log}; start it with serpantinumd start.")
        if any(p != pid and root == shell for p, root, _ in running_shells()):
            return log
    raise RepairError(f"Restart has not completed yet. Check {log}.")
