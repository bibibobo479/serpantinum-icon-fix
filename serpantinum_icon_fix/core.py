"""Offline repair engine. No shell commands, downloads or root writes."""

from __future__ import annotations

import configparser
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


class RepairError(Exception):
    pass


@dataclass
class Change:
    path: Path
    before: bytes | None
    after: bytes
    reason: str


@dataclass
class Plan:
    changes: list[Change] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    shell: Path | None = None
    theme: str = ""


@dataclass
class Context:
    home: Path
    data: Path
    config: Path
    state: Path
    data_dirs: list[Path]

    @classmethod
    def current(cls):
        def xdg(key, default):
            value = os.environ.get(key, "")
            return Path(value) if value.startswith("/") else default

        home = Path.home()
        dirs = [Path(p) for p in os.environ.get(
            "XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p.startswith("/")]
        # Include common Flatpak exports even when the session omitted them.
        dirs += [home / ".local/share/flatpak/exports/share", Path("/var/lib/flatpak/exports/share")]
        return cls(home, xdg("XDG_DATA_HOME", home / ".local/share"),
                   xdg("XDG_CONFIG_HOME", home / ".config"),
                   xdg("XDG_STATE_HOME", home / ".local/state") / "serpantinum-icon-fix",
                   list(dict.fromkeys(dirs)))

    @property
    def icon_roots(self):
        return list(dict.fromkeys([self.home / ".icons", self.data / "icons"] +
                                  [p / "icons" for p in self.data_dirs]))


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_write(path: Path, data: bytes, mode: int = 0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".icon-fix-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def read_index(path: Path):
    try:
        cfg = configparser.ConfigParser(interpolation=None, strict=False)
        cfg.read_string(path.read_text(encoding="utf-8"))
        header = cfg["Icon Theme"]
        directories = [d.strip() for key in ("Directories", "ScaledDirectories")
                       for d in header.get(key, "").split(",") if d.strip()]
        if not header.get("Name") or not directories:
            return None
        for directory in directories:
            if not cfg.has_section(directory) or cfg.getint(directory, "Size", fallback=0) <= 0:
                return None
        return cfg
    except (OSError, UnicodeError, configparser.Error, ValueError, KeyError):
        return None


def effective_index(ctx: Context, theme: str):
    for root in ctx.icon_roots:
        path = root / theme / "index.theme"
        if path.exists():
            return path, read_index(path)
    return None, None


def hicolor_index(ctx: Context) -> bytes:
    """Describe standard sizes and locally installed extra sizes; do not copy icons."""
    sizes = {"scalable": (48, 1), "symbolic": (16, 1)}
    for size in (8, 16, 22, 24, 32, 36, 48, 64, 72, 96, 128, 192, 256, 384, 512, 1024):
        for scale in (1, 2):
            sizes[f"{size}x{size}" + ("@2" if scale == 2 else "")] = (size, scale)
    contexts = {"actions": "Actions", "animations": "Animations", "apps": "Applications",
                "categories": "Categories", "devices": "Devices", "emblems": "Emblems",
                "emotes": "Emotes", "filesystems": "FileSystems", "intl": "International",
                "mimetypes": "MimeTypes", "places": "Places", "status": "Status"}
    directories = {f"{size}/{context}": (*values, contexts[context])
                   for size, values in sizes.items() for context in contexts}
    for root in ctx.icon_roots:
        base = root / "hicolor"
        if not base.is_dir():
            continue
        for current, _, files in os.walk(base):
            if not any(f.lower().endswith((".png", ".svg", ".xpm")) for f in files):
                continue
            rel = Path(current).relative_to(base).as_posix()
            if not re.fullmatch(r"[A-Za-z0-9_@./-]+", rel) or "/" not in rel:
                continue
            top = rel.split("/", 1)[0]
            match = re.fullmatch(r"(\d+)x\d+(?:@(\d+))?", top)
            if match:
                size, scale = int(match[1]), int(match[2] or 1)
            elif top in ("scalable", "symbolic"):
                size, scale = 48, 1
            else:
                continue
            directories[rel] = (size, scale, contexts.get(rel.split("/")[1], "Applications"))
    normal = sorted(k for k, v in directories.items() if v[1] == 1)
    scaled = sorted(k for k, v in directories.items() if v[1] != 1)
    lines = ["# Generated by serpantinum-icon-fix; no icon artwork is included.",
             "[Icon Theme]", "Name=Hicolor", "Comment=Fallback application icons",
             "Hidden=true", "Directories=" + ",".join(normal),
             "ScaledDirectories=" + ",".join(scaled)]
    for directory, (size, scale, context) in sorted(directories.items()):
        lines += ["", f"[{directory}]", f"Size={size}", f"Context={context}"]
        if scale != 1:
            lines.append(f"Scale={scale}")
        if directory.startswith(("scalable/", "symbolic/")):
            lines += ["Type=Scalable", "MinSize=8", "MaxSize=1024"]
        else:
            lines.append("Type=Fixed")
    return ("\n".join(lines) + "\n").encode()


def running_shells():
    found = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            if proc.stat().st_uid != os.getuid():
                continue
            argv = proc.joinpath("cmdline").read_bytes().decode().strip("\0").split("\0")
            if not argv or Path(argv[0]).name not in ("qs", "quickshell"):
                continue
            for flag in ("-p", "--path"):
                if flag in argv:
                    path = Path(argv[argv.index(flag) + 1])
                    if not path.is_absolute():
                        path = proc.joinpath("cwd").resolve() / path
                    candidate = path if path.is_dir() else path.parent
                    if is_shell(candidate):
                        found.append((int(proc.name), candidate.resolve(), path.resolve()))
        except (OSError, ValueError, IndexError, UnicodeError):
            continue
    return found


def is_shell(path):
    return (path / "Shell.qml").is_file() and (path / "launcher/Launcher.qml").is_file()


def discover_shell(ctx: Context, explicit: str | None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if path.is_file():
            path = path.parent
        if not is_shell(path):
            raise RepairError(f"Not a supported Serpantinum QML directory: {path}")
        return path
    active = list(dict.fromkeys(p for _, p, _ in running_shells()))
    if len(active) > 1:
        raise RepairError("Multiple Serpantinum instances found; select one using --shell PATH.")
    if active:
        return active[0]
    candidates = [ctx.data / "serpantinum/src/quickshell",
                  ctx.config / "quickshell/serpantinum", ctx.config / "serpantinum/quickshell",
                  Path("/usr/share/serpantinum/src/quickshell"),
                  Path("/opt/serpantinum/src/quickshell")]
    env_path = os.environ.get("SERPANTINUM_DIR")
    if env_path:
        candidates.insert(0, Path(env_path).expanduser() / "quickshell")
    matches = list(dict.fromkeys(p.resolve() for p in candidates if is_shell(p)))
    if len(matches) > 1:
        raise RepairError("Multiple installations found; select one using --shell PATH.")
    return matches[0] if matches else None


THEME_LINE = re.compile(r"^//@\s*pragma\s+IconTheme\s+([^\s]+)\s*$", re.M)
DOCK_OLD = 'return ic.startsWith("/") ? "file://" + ic : "image://icon/" + ic;'
DOCK_NEW = ('return ic.startsWith("/") ? "file://" + ic : '
            '(Quickshell.iconPath(ic, true) || '
            'Quickshell.iconPath(ic.replace(/\\.(png|svg|xpm|ico)$/i, ""), true));')
LAUNCHER_OLD = 'Quickshell.iconPath(ic) || Quickshell.iconPath(baseName)'
LAUNCHER_NEW = 'Quickshell.iconPath(ic, true) || Quickshell.iconPath(baseName, true)'
ERROR_HANDLER = re.compile(
    r'\n[ \t]*onStatusChanged:\s*\{\s*if\s*\(status === Image.Error\)\s*'
    r'(?:\{\s*failedLoad = true;\s*\}|failedLoad = true;)\s*\}')
PATCH_FILES = ("launcher/Launcher.qml", "dock/DockAppButton.qml",
               "dock/DockRunningButton.qml", "dock/DockPickerRow.qml")


def patch_qml(text: str, launcher: bool) -> str:
    """Only patch the known upstream pattern; unknown versions are left intact."""
    if "ResolvedAppIcon {" in text and "iconName:" in text:
        if "appId:" not in text:
            expr = 'model.desktop_id || ""' if launcher else ('pickerDelegate.resolvedItem.id || ""' if 'id: pIcon' in text else 'model.id || ""')
            text = text.replace('iconName:', 'appId: ' + expr + '\n                iconName:', 1)
        return text
    old, new = (LAUNCHER_OLD, LAUNCHER_NEW) if launcher else (DOCK_OLD, DOCK_NEW)
    if text.count(old) + text.count(new) != 1:
        raise RepairError("Unrecognized icon resolver; file was left unchanged.")
    result = text.replace(old, new)
    if launcher:
        old_return = 'return "image://icon/" + baseName;'
        if old_return in result:
            if result.count(old_return) != 1:
                raise RepairError("Ambiguous launcher fallback; file was left unchanged.")
            result = result.replace(old_return, 'return "";')
    if 'property bool failedLoad: false' in result:
        if result.count('property bool failedLoad: false') != 1 or len(ERROR_HANDLER.findall(result)) != 1:
            raise RepairError("Unrecognized image error handler; file was left unchanged.")
        result = result.replace('property bool failedLoad: false',
                                'readonly property bool failedLoad: status === Image.Error')
        result = ERROR_HANDLER.sub('', result, count=1)
    elif 'readonly property bool failedLoad: status === Image.Error' not in result:
        raise RepairError("Unrecognized image state; file was left unchanged.")
    if not re.search(r'^import Quickshell(?:\s+\d+(?:\.\d+)?)?\s*$', result, re.M):
        result = result.replace('import QtQuick\n', 'import QtQuick\nimport Quickshell\n', 1)
        if not re.search(r'^import Quickshell\s*$', result, re.M):
            raise RepairError("Cannot add Quickshell import safely.")
    # Replace only the validated application image, preserving its layout and fallback text.
    marker = 'readonly property bool failedLoad: status === Image.Error'
    pos = result.index(marker)
    start = result.rfind('Image {', 0, pos)
    if start < 0: raise RepairError("Application Image block not found.")
    result = result[:start] + result[start:].replace('Image {', 'ResolvedAppIcon {', 1)
    result = result.replace(marker, '')
    pos = result.index('source: {', start)
    depth, end = 1, pos + len('source: {')
    while depth and end < len(result):
        if result[end] == '{': depth += 1
        elif result[end] == '}': depth -= 1
        end += 1
    expr = '(model.fontIcon ? "" : model.icon || "")' if launcher else ('pickerDelegate.resolvedItem.icon || ""' if 'id: pIcon' in result else 'model.icon || ""')
    result = result[:pos] + 'appId: ' + ('model.desktop_id || \"\"' if launcher else ('pickerDelegate.resolvedItem.id || \"\"' if 'id: pIcon' in result else 'model.id || \"\"')) + '\n                iconName: ' + expr + result[end:]
    if 'import "../reusables"' not in result:
        result = 'import "../reusables"\n' + result
    return result


def writable_parent(path):
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    return os.access(parent, os.W_OK)


def plan_repair(ctx: Context, shell=None, theme="auto") -> Plan:
    plan = Plan(shell=discover_shell(ctx, shell))
    index_path, index = effective_index(ctx, "hicolor")
    if index is None:
        # A malformed legacy ~/.icons index would shadow the XDG copy.
        target = index_path if index_path and index_path.is_relative_to(ctx.home) else ctx.data / "icons/hicolor/index.theme"
        plan.changes.append(Change(target, target.read_bytes() if target.exists() else None,
                                   hicolor_index(ctx), "Restore missing or invalid hicolor index"))
    else:
        plan.notes.append(f"Hicolor index is valid: {index_path}")
    if plan.shell is None:
        plan.warnings.append("Serpantinum was not found. Icon index repair only; use --shell PATH for QML fixes.")
        return plan
    root_file = plan.shell / "Shell.qml"
    root_text = root_file.read_text()
    current = THEME_LINE.search(root_text)
    selected = current[1] if current else ""
    if theme != "auto":
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+", theme):
            raise RepairError("Invalid theme name.")
        if theme != "hicolor" and effective_index(ctx, theme)[1] is None:
            raise RepairError(f"Theme is not installed or its index is invalid: {theme}")
        selected = theme
    elif not selected or effective_index(ctx, selected)[1] is None:
        selected = next((name for name in ("Papirus", "Papirus-Dark", "breeze", "Adwaita")
                         if effective_index(ctx, name)[1] is not None), "hicolor")
    plan.theme = selected
    updated = THEME_LINE.sub(f"//@ pragma IconTheme {selected}", root_text, count=1) if current else f"//@ pragma IconTheme {selected}\n" + root_text
    candidates = [(root_file, root_text, updated, f"Set shell icon theme: {selected}")]
    for rel in PATCH_FILES:
        path = plan.shell / rel
        if not path.is_file():
            plan.warnings.append(f"Missing QML component, skipped: {rel}")
            continue
        old = path.read_text()
        try:
            new = patch_qml(old, rel.startswith("launcher/"))
            candidates.append((path, old, new, "Resolve application identity and retry alternative icon files"))
        except RepairError as exc:
            plan.warnings.append(f"{rel}: {exc}")
    # Keep runtime dependencies outside the tree replaced by the upstream updater.
    module = ctx.data / "serpantinum-icon-fix/qml"
    module_import = 'import ' + json.dumps(module.as_uri()) + ' as IconFix'
    migrated = []
    for path, old, new, reason in candidates:
        if path.name != "Shell.qml":
            new = re.sub(r'(?<![\w.])ResolvedAppIcon\s*\{', 'IconFix.ResolvedAppIcon {', new)
            new = re.sub(r'^import \"[^\"\n]+\" as IconFix\s*$', '', new, flags=re.M).lstrip('\n')
            new = module_import + "\n" + new
        migrated.append((path, old, new, reason))
    assets = Path(__file__).parent
    dependencies = []
    for name in ("IconResolver.qml", "ResolvedAppIcon.qml"):
        path = module / name
        content = (assets / name).read_text().replace("__THEME__", selected).replace("__PACKAGE__", str(assets.parent))
        dependencies.append((path, path.read_text() if path.exists() else "", content, "Install update-independent icon component"))
    path = module / "qmldir"
    content = "singleton IconResolver 1.0 IconResolver.qml\nResolvedAppIcon 1.0 ResolvedAppIcon.qml\n"
    dependencies.append((path, path.read_text() if path.exists() else "", content, "Register private icon components"))
    # Dependencies must exist before consumers can reload. Upstream qmldir is untouched.
    candidates = dependencies + migrated
    for path, old, new, reason in candidates:
        if new == old:
            continue
        if (path.exists() and not os.access(path, os.W_OK)) or not writable_parent(path):
            plan.warnings.append(f"Read-only installation, skipped: {path}. Use a writable user copy or your Nix configuration.")
            continue
        # Resolve symlinks so atomic writes preserve the installation's link layout.
        plan.changes.append(Change(path.resolve(), old.encode() if path.exists() else None, new.encode(), reason))
    plan.notes.append(f"Shell: {plan.shell}; icon theme: {selected}")
    return plan


def _verify(path, expected):
    actual = path.read_bytes() if path.exists() else None
    if actual != expected:
        raise RepairError(f"File changed since inspection; refusing to overwrite: {path}")


def apply_plan(ctx: Context, plan: Plan) -> Path | None:
    if os.geteuid() == 0:
        raise RepairError("Run as your desktop user, without sudo.")
    if not plan.changes:
        return None
    ctx.state.mkdir(parents=True, exist_ok=True)
    with (ctx.state / "repair.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for change in plan.changes:
            _verify(change.path, change.before)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ")
        backup = ctx.state / "backups" / stamp
        backup.mkdir(parents=True, mode=0o700)
        entries = []
        for i, change in enumerate(plan.changes):
            mode = stat.S_IMODE(change.path.stat().st_mode) if change.before is not None else 0o644
            name = f"{i}.original"
            if change.before is not None:
                atomic_write(backup / name, change.before, 0o600)
            entries.append({"path": str(change.path), "original": name if change.before is not None else None,
                            "before": digest(change.before) if change.before is not None else None,
                            "after": digest(change.after), "mode": mode})
        manifest = {"format": 1, "status": "prepared", "entries": entries}
        manifest_path = backup / "manifest.json"
        atomic_write(manifest_path, json.dumps(manifest, indent=2).encode(), 0o600)
        written = []
        try:
            for change, entry in zip(plan.changes, entries):
                _verify(change.path, change.before)
                atomic_write(change.path, change.after, entry["mode"])
                written.append((change, entry))
        except Exception:
            for change, entry in reversed(written):
                _verify(change.path, change.after)
                if change.before is None:
                    change.path.unlink()
                else:
                    atomic_write(change.path, change.before, entry["mode"])
            manifest["status"] = "rolled_back"
            atomic_write(manifest_path, json.dumps(manifest, indent=2).encode(), 0o600)
            raise
        manifest["status"] = "applied"
        atomic_write(manifest_path, json.dumps(manifest, indent=2).encode(), 0o600)
        return backup


def restore_latest(ctx: Context) -> Path:
    if os.geteuid() == 0:
        raise RepairError("Run as your desktop user, without sudo.")
    ctx.state.mkdir(parents=True, exist_ok=True)
    with (ctx.state / "repair.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifests = sorted((ctx.state / "backups").glob("*/manifest.json"), reverse=True)
        for path in manifests:
            manifest = json.loads(path.read_text())
            if manifest.get("status") == "applied":
                break
        else:
            raise RepairError("No applied repair to restore.")
        originals = []
        for entry in manifest["entries"]:
            target = Path(entry["path"])
            if not target.exists() or digest(target.read_bytes()) != entry["after"]:
                raise RepairError(f"File changed after repair; restore cancelled without changes: {target}")
            original = (path.parent / entry["original"]).read_bytes() if entry["original"] else None
            if original is not None and digest(original) != entry["before"]:
                raise RepairError(f"Backup checksum mismatch: {target}")
            originals.append((target, original, entry["mode"]))
        for target, original, mode in reversed(originals):
            if original is None:
                target.unlink()
            else:
                atomic_write(target, original, mode)
        manifest["status"] = "restored"
        atomic_write(path, json.dumps(manifest, indent=2).encode(), 0o600)
        return path.parent
