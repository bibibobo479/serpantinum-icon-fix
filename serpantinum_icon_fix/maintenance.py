"""Debounced, non-restarting repair after upstream updates."""
import hashlib
import json
import time

from .core import Context, RepairError, apply_plan, atomic_write, plan_repair


def maintain(ctx=None, now=None):
    ctx = ctx or Context.current()
    now = time.time() if now is None else now
    plan = plan_repair(ctx)
    if plan.shell is None:
        return "Serpantinum is not installed; waiting."
    if not plan.changes:
        return "Icon repair is current. " + "; ".join(plan.warnings)
    # Include the entire QML tree: wait while the installer is copying other files too.
    snapshot = [(str(p), p.stat().st_mtime_ns, p.stat().st_size)
                for p in sorted(plan.shell.rglob('*')) if p.is_file()]
    snapshot += [(str(c.path), hashlib.sha256(c.before or b'').hexdigest(),
                  hashlib.sha256(c.after).hexdigest()) for c in plan.changes]
    fingerprint = hashlib.sha256(json.dumps(snapshot).encode()).hexdigest()
    pending = ctx.state / 'maintenance-pending.json'
    try:
        previous = json.loads(pending.read_text())
    except (OSError, ValueError):
        previous = {}
    if (previous.get('fingerprint') != fingerprint or
            not isinstance(previous.get('since'), (int, float)) or
            now < previous['since']):
        atomic_write(pending, json.dumps({'fingerprint': fingerprint, 'since': now}).encode(), 0o600)
        return "Update detected; waiting for files to settle."
    if now - previous['since'] < 20:
        return "Waiting for files to settle."
    backup = apply_plan(ctx, plan)
    pending.unlink(missing_ok=True)
    return f"Repaired icons; backup: {backup}. " + '; '.join(plan.warnings)


def main():
    try:
        print(maintain())
        return 0
    except (OSError, ValueError, RepairError) as exc:
        print(f"Repair deferred: {exc}")
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
