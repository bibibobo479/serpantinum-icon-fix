#!/usr/bin/env python3
"""Install only for the current user. Never modifies Serpantinum itself."""
import os
from pathlib import Path
import shutil
import sys
import subprocess

if os.geteuid() == 0:
    sys.exit("Run without sudo.")
source = Path(__file__).resolve().parent
home = Path.home()
data = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share")))
if not data.is_absolute():
    data = home / ".local/share"
target = data / "serpantinum-icon-fix"
target.mkdir(parents=True, exist_ok=True)
if source != target:
    shutil.copytree(source / "serpantinum_icon_fix", target / "serpantinum_icon_fix", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("README.md", "LICENSE", "NOTICE.md"):
        shutil.copy2(source / name, target / name)
launcher = home / ".local/bin/serpantinum-icon-fix"
launcher.parent.mkdir(parents=True, exist_ok=True)
launcher.write_text('#!/usr/bin/env python3\nimport sys\nsys.path.insert(0, ' + repr(str(target)) +
                    ')\nfrom serpantinum_icon_fix.__main__ import main\nsys.exit(main())\n')
launcher.chmod(0o755)
# Desktop Exec quoting follows the desktop-entry spec, not shell quoting.
quoted = '"' + str(launcher).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
desktop = data / "applications/serpantinum-icon-fix.desktop"
desktop.parent.mkdir(parents=True, exist_ok=True)
desktop.write_text('[Desktop Entry]\nType=Application\nName=Serpantinum Icon Fix\n'
                   'Comment=Repair missing Serpantinum application icons\n'
                   'Comment[ru]=Исправление отсутствующих иконок Serpantinum\n'
                   f'Exec={quoted} --gui\nIcon=preferences-desktop-theme\nTerminal=false\n'
                   'Categories=Settings;\nStartupNotify=false\n')
print(f"Installed: {launcher}\nApplication menu: Serpantinum Icon Fix\nRun it without sudo.")

# A user timer survives replacement of the Serpantinum installation itself.
config = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
if not config.is_absolute():
    config = home / ".config"
units = config / "systemd/user"
units.mkdir(parents=True, exist_ok=True)
# systemd expands percent specifiers, including inside quoted arguments.
def unit_arg(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
(units / "serpantinum-icon-fix.service").write_text(
    '[Unit]\nDescription=Restore Serpantinum icons after updates\n'
    '[Service]\nType=oneshot\n'
    f'ExecStart={unit_arg(launcher)} --maintain\n')
(units / "serpantinum-icon-fix.timer").write_text(
    '[Unit]\nDescription=Check Serpantinum icon compatibility after updates\n'
    '[Timer]\nOnStartupSec=30\nOnUnitInactiveSec=15\nAccuracySec=5\n'
    '[Install]\nWantedBy=timers.target\n')
if shutil.which("systemctl"):
    reload = subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    if reload.returncode == 0:
        enabled = subprocess.run(["systemctl", "--user", "enable", "--now", "serpantinum-icon-fix.timer"],
                                 capture_output=True)
        if enabled.returncode == 0:
            print("Automatic update repair enabled (no shell restarts).")
        else:
            print("Timer activation failed: " + enabled.stderr.decode(errors="replace"))
    else:
        print("No user systemd session. Enable serpantinum-icon-fix.timer later, or run --apply after updates.")
else:
    print("systemd is unavailable; run serpantinum-icon-fix --apply after updates.")
