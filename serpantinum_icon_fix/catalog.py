"""Read-only fallback catalog for application icons missed by Qt theme lookup."""
import configparser
import json
import os
from pathlib import Path
from .core import Context

EXTS = {".png", ".svg", ".svgz", ".xpm", ".ico", ".webp", ".jpg", ".jpeg"}

def build(theme="Papirus"):
    ctx = Context.current()
    themes = []
    def inherit(name):
        if name in themes: return
        themes.append(name)
        for root in ctx.icon_roots:
            cfg = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cfg.read(root / name / "index.theme")
                parents = cfg.get("Icon Theme", "Inherits", fallback="")
            except (OSError, configparser.Error): continue
            for parent in parents.split(","):
                if parent.strip(): inherit(parent.strip())
    inherit(theme)
    inherit("hicolor")
    for name in ("Adwaita", "breeze", "Papirus"): inherit(name)
    icons = {}
    roots = [(root / name, rank) for rank, name in enumerate(themes) for root in ctx.icon_roots]
    roots += [(p / "pixmaps", len(themes)) for p in [ctx.data] + ctx.data_dirs]
    roots += [(root, len(themes)+1) for root in ctx.icon_roots]
    seen = set()
    for root, rank in roots:
        if not root.is_dir(): continue
        for directory, dirs, files in os.walk(root, followlinks=True):
            # Papirus theme directories are symlinks; prevent cycles and duplicate scans.
            try:
                real = str(Path(directory).resolve())
            except (OSError, RuntimeError):
                dirs[:] = []; continue
            if real in seen:
                dirs[:] = []; continue
            seen.add(real)
            for filename in files:
                p = Path(directory) / filename
                if p.suffix.lower() not in EXTS or not p.is_file(): continue
                # Prefer application artwork near launcher size, keep alternatives for decoder errors.
                parts = p.parts
                size = next((int(s.split("x")[0]) for s in reversed(parts) if s.split("x")[0].isdigit()), 64)
                score = (rank, 0 if "apps" in parts else 1, abs(size-64), 0 if p.suffix == ".svg" else 1)
                icons.setdefault(p.stem, []).append((score, p.as_uri()))
    aliases = {}
    desktops = set()
    for root in [ctx.data] + ctx.data_dirs:
        appdir = root / "applications"
        if not appdir.is_dir(): continue
        for p in sorted(appdir.rglob("*.desktop")):
            desktop_id = str(p.relative_to(appdir)).replace("/", "-")[:-8]
            if desktop_id in desktops: continue
            desktops.add(desktop_id)
            cfg = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cfg.read(p, encoding="utf-8")
                e = cfg["Desktop Entry"]
                if e.get("Hidden", "").lower() == "true": continue
                icon = e.get("Icon", "").strip()
                if not icon: continue
                keys = [desktop_id, e.get("StartupWMClass", ""), e.get("Name", "")]
                import shlex
                try:
                    args = shlex.split(e.get("Exec", ""))
                    if args and Path(args[0]).name not in ("env", "flatpak", "sh", "bash"):
                        keys.append(Path(args[0]).name)
                except ValueError: pass
                for key in keys:
                    if key: aliases.setdefault(key.casefold(), icon)
            except (OSError, UnicodeError, configparser.Error, KeyError): continue
    return {"icons": {k: list(dict.fromkeys(url for _, url in sorted(v)))[:8] for k,v in icons.items()}, "aliases": aliases}

if __name__ == "__main__":
    import sys
    print(json.dumps(build(sys.argv[1] if len(sys.argv)>1 else "Papirus"), separators=(",", ":")))
