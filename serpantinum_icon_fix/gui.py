"""Optional Tk UI. Repair work runs off the UI thread."""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from . import __version__
from .core import apply_plan, discover_shell, plan_repair, restore_latest
from .restart import restart_shell


def launch(ctx, args):
    ru = os.environ.get("LANG", "").startswith("ru")
    def tr(en, russian):
        return russian if ru else en

    window = tk.Tk()
    window.title("Serpantinum Icon Fix")
    window.geometry("830x590")
    window.minsize(650, 450)
    style = ttk.Style(window)
    style.theme_use("clam")
    style.configure("TFrame", background="#101c26")
    style.configure("TLabel", background="#101c26", foreground="#ecf4f8")
    style.configure("Title.TLabel", font=("Sans", 23, "bold"))
    style.configure("TButton", padding=(12, 8))
    window.configure(bg="#101c26")
    frame = ttk.Frame(window, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Serpantinum Icon Fix", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, text=tr("Real app icons. Automatic backups. No sudo.",
                             "Иконки приложений · Резервные копии · Без sudo")).pack(anchor="w", pady=(6, 18))
    selection = ttk.Frame(frame)
    selection.pack(fill="x")
    shell = tk.StringVar(value=args.shell or "")
    ttk.Label(selection, text=tr("Shell folder:", "Папка оболочки:")).pack(side="left")
    entry = ttk.Entry(selection, textvariable=shell)
    entry.pack(side="left", fill="x", expand=True, padx=8)
    def browse():
        folder = filedialog.askdirectory(title="Select Serpantinum quickshell folder")
        if folder:
            shell.set(folder)
    pick = ttk.Button(selection, text=tr("Browse", "Выбрать"), command=browse)
    pick.pack(side="left")
    status = tk.StringVar(value=tr("Starting repair…", "Запускаю исправление…"))
    ttk.Label(frame, textvariable=status, wraplength=730).pack(anchor="w", pady=(18, 8))
    output = tk.Text(frame, bg="#08121b", fg="#cce3ee", insertbackground="white",
                     font=("Monospace", 10), relief="flat", padx=12, pady=12, wrap="word")
    output.pack(fill="both", expand=True)
    output.configure(state="disabled")
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(14, 8))
    ttk.Label(frame, text=tr(f"v{__version__} · Backups: {ctx.state / 'backups'}",
                             f"v{__version__} · Копии: {ctx.state / 'backups'}"), wraplength=730).pack(anchor="w")
    events = queue.Queue()
    controls = [entry, pick]
    busy = False

    def append(text):
        output.configure(state="normal")
        output.insert("end", text + "\n")
        output.see("end")
        output.configure(state="disabled")

    def work(action, selected):
        try:
            if action == "restore":
                folder = restore_latest(ctx)
                events.put(("log", f"Restored: {folder}"))
                message = tr("Restored. Restart the shell to clear its cache.", "Откат выполнен. Перезапусти оболочку для очистки кэша.")
            elif action == "restart":
                path = restart_shell(ctx, discover_shell(ctx, selected))
                events.put(("log", f"Restart log: {path}"))
                message = tr("Serpantinum restarted.", "Serpantinum перезапущен.")
            else:
                plan = plan_repair(ctx, selected, args.theme)
                for text in plan.notes:
                    events.put(("log", text))
                for change in plan.changes:
                    events.put(("log", f"{change.reason}\n  {change.path}"))
                if action == "apply":
                    folder = apply_plan(ctx, plan)
                    if folder:
                        events.put(("log", f"Backup: {folder}"))
                    message = tr(f"Applied {len(plan.changes)} changes. Restart Serpantinum if icons are still cached.",
                                 f"Применено изменений: {len(plan.changes)}. Перезапусти Serpantinum, если остался старый кэш иконок.")
                    if args.restart:
                        restart_shell(ctx, plan.shell)
                        message = tr("Repaired and restarted.", "Исправлено. Оболочка перезапущена.")
                else:
                    message = tr(f"Check complete: {len(plan.changes)} changes available. No files written.",
                                 f"Проверка: доступно изменений — {len(plan.changes)}. Файлы не изменены.")
                for warning in plan.warnings:
                    events.put(("log", "WARNING: " + warning))
                if plan.warnings:
                    message = tr("Completed with limitations — see the report below.", "Выполнено с ограничениями — подробности в отчёте ниже.")
            events.put(("done", message))
        except Exception as exc:
            events.put(("log", "ERROR: " + str(exc)))
            events.put(("done", tr("Could not complete. See the report.", "Не удалось завершить. Смотри отчёт.")))

    def start(action):
        nonlocal busy
        if busy:
            return
        busy = True
        status.set(tr("Working…", "Выполняется…"))
        for control in controls:
            control.configure(state="disabled")
        selected = shell.get().strip() or None
        threading.Thread(target=work, args=(action, selected), daemon=False).start()

    for action, caption in (("check", tr("Check", "Проверить")), ("apply", tr("Repair", "Исправить")),
                            ("restore", tr("Undo last repair", "Отменить исправление")),
                            ("restart", tr("Restart Serpantinum", "Перезапустить Serpantinum"))):
        button = ttk.Button(buttons, text=caption, command=lambda a=action: start(a))
        button.pack(side="left", padx=(0, 6))
        controls.append(button)

    def poll():
        nonlocal busy
        while not events.empty():
            kind, value = events.get_nowait()
            if kind == "log":
                append(value)
            else:
                status.set(value)
                busy = False
                for control in controls:
                    control.configure(state="normal")
        window.after(100, poll)

    def close():
        if busy:
            status.set(tr("Finishing the current operation before closing…", "Дождись завершения текущей операции…"))
        else:
            window.destroy()
    window.protocol("WM_DELETE_WINDOW", close)
    window.after(100, poll)
    window.after(400, lambda: start("apply"))
    window.mainloop()
    return 0
