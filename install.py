#!/usr/bin/env python3
"""Install only for the current user. Never modifies Serpantinum itself."""
import os
from pathlib import Path
import shutil
import sys

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
