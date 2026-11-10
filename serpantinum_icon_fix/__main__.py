import argparse
import json
import os
import sys
import subprocess

from . import __version__
from .core import Context, RepairError, apply_plan, plan_repair, restore_latest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Repair Serpantinum icons for the current desktop user, without sudo.")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--maintain", action="store_true", help="repair settled upstream updates without restarting the shell")
    actions.add_argument("--check", "--dry-run", action="store_true", help="report changes without writing files")
    actions.add_argument("--apply", action="store_true", help="apply repairs in the terminal")
    actions.add_argument("--restore", action="store_true", help="undo the latest applied repair if files are unchanged")
    actions.add_argument("--gui", action="store_true", help="open a window and automatically apply repairs")
    parser.add_argument("--shell", metavar="PATH", help="Serpantinum quickshell directory or Shell.qml")
    parser.add_argument("--theme", default="auto", help="installed icon theme (default: preserve valid shell theme, otherwise auto-select)")
    parser.add_argument("--restart", action="store_true", help="restart the selected daemon-managed shell after applying or restoring")
    parser.add_argument("--json", action="store_true", help="print machine-readable output; implies terminal mode")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    if args.maintain:
        if args.restart or args.shell or args.theme != "auto" or args.json:
            parser.error("--maintain cannot be combined with restart, shell, theme or json options")
        from .maintenance import main as maintain_main
        return maintain_main()
    if args.check and args.restart:
        parser.error("--check cannot be combined with --restart")
    if args.gui and args.json:
        parser.error("--gui cannot be combined with --json")
    try:
        if os.geteuid() == 0:
            raise RepairError("Run as your desktop user, without sudo.")
        ctx = Context.current()
        graphical = args.gui or (not any((args.check, args.apply, args.restore, args.json))
                                and bool(os.environ.get("DISPLAY")))
        if graphical:
            try:
                from .gui import launch
                return launch(ctx, args)
            except ImportError as exc:
                if args.gui:
                    raise RepairError("GUI requires Tk: install tk (Arch) / python3-tk (Debian) / python3-tkinter (Fedora), or use --apply.") from exc
                print("Tk is unavailable; applying in terminal mode.", file=sys.stderr)
        result = {"version": __version__, "warnings": []}
        if args.restore:
            result["restored"] = str(restore_latest(ctx))
        else:
            plan = plan_repair(ctx, args.shell, args.theme)
            result.update(shell=str(plan.shell) if plan.shell else None, theme=plan.theme,
                          changes=[{"path": str(c.path), "reason": c.reason} for c in plan.changes],
                          notes=plan.notes, warnings=plan.warnings, dry_run=args.check)
            if not args.check:
                backup = apply_plan(ctx, plan)
                result["backup"] = str(backup) if backup else None
                result["applied"] = len(plan.changes)
        if args.restart:
            from .core import discover_shell
            from .restart import restart_shell
            result["restart_log"] = str(restart_shell(ctx, discover_shell(ctx, args.shell)))
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            for note in result.get("notes", []):
                print(note)
            for change in result.get("changes", []):
                print(f"{'Would change' if args.check else 'Updated'}: {change['path']} — {change['reason']}")
            for warning in result["warnings"]:
                print("WARNING:", warning)
            if result.get("backup"):
                print("Backup:", result["backup"])
            if result.get("restored"):
                print("Restored:", result["restored"])
            elif not result.get("changes"):
                print("No file changes needed.")
            if not args.check and result.get("changes") and not args.restart:
                print("Restart Serpantinum to clear Qt's icon cache. Applications can remain open.")
        return 2 if result["warnings"] else 0
    except (RepairError, OSError, ValueError, subprocess.SubprocessError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
