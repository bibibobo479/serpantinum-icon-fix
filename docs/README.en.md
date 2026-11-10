# Serpantinum Icon Fix

A user-local tool for missing application icons and purple/black checkerboards in [Serpantinum](https://github.com/ilyamiro/serpantinum). Independent project; not an official Serpantinum component.

Requires Linux and Python 3.10+. The CLI uses only Python's standard library. The optional GUI needs Tk and X11/XWayland. No root access, network requests or package installations are needed during repairs.

```bash
git clone https://github.com/bibibobo479/serpantinum-icon-fix.git
cd serpantinum-icon-fix
./run.sh
```

Launching without arguments opens the GUI when `DISPLAY` is available and **automatically applies the repair**. Without a graphical session or Tk it applies in terminal mode. Use `--check` for inspection without writes.

```bash
./run.sh --check
./run.sh --apply
./run.sh --apply --restart
./run.sh --restore
./run.sh --check --json
./run.sh --apply --shell /path/to/serpantinum/src/quickshell --theme Papirus
python3 install.py  # Add a per-user launcher and desktop menu entry
```

Run as your desktop user, never with sudo. Each user runs their own repair. Paths come from XDG variables, common locations and the running shell; no account name is hardcoded. Tk package names: `tk` (Arch), `python3-tk` (Debian/Ubuntu), `python3-tkinter` (Fedora).

The tool restores a missing or malformed hicolor index in the user's icon directory, preserves a valid explicit shell theme or chooses an installed fallback, and patches recognized launcher/dock icon-loading code. Missing icons return the shell's existing fallback instead of Quickshell's checkerboard. Image errors no longer remain stuck after the source changes. Existing valid hicolor indexes are preserved.

Restart Serpantinum to clear Qt's icon cache. `--restart` and the GUI button support exactly one daemon-managed instance; other launch methods require restarting through your session manager. Normal applications remain open.

Backups, hashes and original permissions are saved under `$XDG_STATE_HOME/serpantinum-icon-fix/backups` (default `~/.local/state/serpantinum-icon-fix/backups`). Repeated repairs are idempotent. Restore refuses to overwrite files changed after repair, including upstream updates.

QML patches were tested on Serpantinum **2.3.0 / a62f825**. Unknown upstream code is skipped with a warning; read-only system and Nix installations are not modified with elevated permissions. Adapt those installations through your configuration or a writable user copy. The tool does not recreate deleted icon images, fix arbitrary window-class mappings, or guarantee repairs for every system-tray icon. Shell updates can overwrite patches; the installed user timer reapplies recognized patches after files settle. Without systemd, rerun --apply manually.

Exit status: `0` success, `1` error, `2` partial result/warnings. `--check` never writes files. Tests: `python3 -m unittest discover -s tests -v`.

License: AGPL-3.0-only. See [NOTICE](../NOTICE.md) and [validation](VALIDATION.md).

## Update resilience (1.1.0)

Runtime components live outside the upstream tree, in `$XDG_DATA_HOME/serpantinum-icon-fix/qml`, and consumers use an explicit `IconFix` import. Replacing upstream `reusables/qmldir` no longer breaks patched consumers. Applying migrates legacy patches; upstream registrations are left untouched.

`python3 install.py` also enables `serpantinum-icon-fix.timer` when user systemd is available. It checks about every 15–20 seconds and waits for at least 20 seconds of unchanged QML files before repairing. It never starts or restarts the shell. Unknown future QML is skipped; backups and concurrent-edit checks still apply. A paused or interrupted installer can also leave stable files: finish upstream installation in that case.

Inspect with `systemctl --user status serpantinum-icon-fix.timer` and `journalctl --user -u serpantinum-icon-fix.service`. Disable with `systemctl --user disable --now serpantinum-icon-fix.timer` before using `--restore`, otherwise maintenance reapplies the repair. Non-systemd/custom installations can use `--apply` manually. Full upstream replacements may temporarily restore ordinary icon behavior until maintenance runs.
