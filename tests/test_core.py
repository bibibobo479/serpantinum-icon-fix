import configparser
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from serpantinum_icon_fix import core


def dock_source():
    return '''import QtQuick
import QtQuick.Layouts
Item {
    Image {
        property bool failedLoad: false
        source: {
            let ic = model.icon || "";
            if (!ic) return "";
            if (ic.startsWith("file://") || ic.startsWith("image://")) return ic;
            ''' + core.DOCK_OLD + '''
        }
        onStatusChanged: {
            if (status === Image.Error) failedLoad = true;
        }
    }
}
'''


def launcher_source():
    return '''import QtQuick
import Quickshell
Item {
    Image {
        property bool failedLoad: false
        source: {
            let ic = "test";
            let baseName = ic.replace(/\\.(png|svg|xpm|ico)$/i, "");
            let resolved = ''' + core.LAUNCHER_OLD + ''';
            if (resolved) return resolved;
            return "image://icon/" + baseName;
        }
        onStatusChanged: {
            if (status === Image.Error) {
                failedLoad = true;
            }
        }
    }
}
'''


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.system = self.root / "system/share"
        self.ctx = core.Context(self.home, self.home / "data", self.home / "config",
                                self.home / "state", [self.system])
        self.shell = self.ctx.data / "serpantinum/src/quickshell"
        (self.shell / "launcher").mkdir(parents=True)
        (self.shell / "dock").mkdir()
        (self.shell / "reusables").mkdir()
        (self.shell / "reusables/qmldir").write_text("")
        (self.shell / "Shell.qml").write_text('import Quickshell\nShellRoot {}\n')
        (self.shell / "launcher/Launcher.qml").write_text(launcher_source())
        for rel in core.PATCH_FILES[1:]:
            (self.shell / rel).write_text(dock_source())
        self.theme("Papirus")
        self.running = patch.object(core, "running_shells", return_value=[])
        self.running.start()
        self.addCleanup(self.running.stop)
        # CI containers can run as root; production intentionally refuses root.
        self.uid = patch.object(core.os, "geteuid", return_value=1000)
        self.uid.start()
        self.addCleanup(self.uid.stop)

    def theme(self, name):
        path = self.system / "icons" / name / "index.theme"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[Icon Theme]\nName=' + name + '\nDirectories=48x48/apps\n\n[48x48/apps]\nSize=48\nType=Fixed\n')
        return path

    def plan(self, **kwargs):
        return core.plan_repair(self.ctx, str(self.shell), **kwargs)

    def test_missing_index_repair_is_user_local_and_idempotent(self):
        plan = self.plan()
        self.assertEqual(len(plan.changes), 9)
        self.assertEqual(plan.warnings, [])
        backup = core.apply_plan(self.ctx, plan)
        self.assertTrue((backup / 'manifest.json').exists())
        self.assertIsNotNone(core.read_index(self.ctx.data / 'icons/hicolor/index.theme'))
        self.assertFalse((self.system / 'icons/hicolor/index.theme').exists())
        self.assertEqual(self.plan().changes, [])
        self.assertEqual(self.plan().warnings, [])

    def test_healthy_system_index_is_not_shadowed(self):
        system_index = self.theme('hicolor')
        original = system_index.read_bytes()
        plan = self.plan()
        self.assertFalse(any(c.path.name == 'index.theme' for c in plan.changes))
        core.apply_plan(self.ctx, plan)
        self.assertEqual(system_index.read_bytes(), original)
        self.assertFalse((self.ctx.data / 'icons/hicolor/index.theme').exists())

    def test_invalid_legacy_index_and_extra_scaled_directories(self):
        path = self.home / '.icons/hicolor/index.theme'
        path.parent.mkdir(parents=True)
        path.write_text('[Icon Theme]\nName=Broken\nDirectories=missing\n')
        custom = self.system / 'icons/hicolor/80x80@3/apps'
        custom.mkdir(parents=True)
        (custom / 'test.svg').write_text('<svg/>')
        plan = self.plan()
        self.assertEqual(plan.changes[0].path, path)
        core.apply_plan(self.ctx, plan)
        cfg = core.read_index(path)
        self.assertEqual(cfg.getint('80x80@3/apps', 'Scale'), 3)
        self.assertIn('80x80@3/apps', cfg['Icon Theme']['ScaledDirectories'])

    def test_existing_custom_theme_is_preserved(self):
        self.theme('Custom')
        path = self.shell / 'Shell.qml'
        path.write_text('//@ pragma IconTheme Custom\n' + path.read_text())
        plan = self.plan()
        self.assertEqual(plan.theme, 'Custom')
        self.assertNotIn(path, [c.path for c in plan.changes])

    def test_uninstalled_explicit_theme_aborts_before_writing(self):
        with self.assertRaises(core.RepairError):
            self.plan(theme='Missing')
        self.assertFalse(self.ctx.state.exists())
        self.assertFalse((self.ctx.data / 'icons').exists())

    def test_unknown_qml_is_reported_and_not_modified(self):
        path = self.shell / 'dock/DockAppButton.qml'
        unknown = 'import QtQuick\nItem { property string icon: "new upstream design" }\n'
        path.write_text(unknown)
        plan = self.plan()
        self.assertTrue(any('DockAppButton.qml' in w for w in plan.warnings))
        core.apply_plan(self.ctx, plan)
        self.assertEqual(path.read_text(), unknown)

    def test_qml_import_fallback_and_error_recovery(self):
        dock = core.patch_qml(dock_source(), False)
        self.assertEqual(dock.count('import Quickshell\n'), 1)
        self.assertIn('ResolvedAppIcon {', dock)
        self.assertIn('iconName: model.icon', dock)
        self.assertNotIn('failedLoad = true', dock)
        self.assertIn('appId: model.id', dock)
        self.assertEqual(core.patch_qml(dock, False), dock)
        launcher = core.patch_qml(launcher_source(), True)
        self.assertNotIn('return "image://icon/" + baseName', launcher)
        self.assertEqual(core.patch_qml(launcher, True), launcher)

    def test_restore_returns_original_bytes_and_removes_created_index(self):
        before = {p: p.read_bytes() for p in self.shell.rglob('*.qml')}
        backup = core.apply_plan(self.ctx, self.plan())
        self.assertEqual(core.restore_latest(self.ctx), backup)
        for path, expected in before.items():
            self.assertEqual(path.read_bytes(), expected)
        self.assertFalse((self.ctx.data / 'icons/hicolor/index.theme').exists())
        with self.assertRaises(core.RepairError):
            core.restore_latest(self.ctx)

    def test_restore_never_clobbers_later_user_changes(self):
        core.apply_plan(self.ctx, self.plan())
        path = self.shell / 'Shell.qml'
        path.write_text(path.read_text() + '// user edit\n')
        before = {p: p.read_bytes() for p in self.shell.rglob('*.qml')}
        with self.assertRaises(core.RepairError):
            core.restore_latest(self.ctx)
        for p, expected in before.items():
            self.assertEqual(p.read_bytes(), expected)
        self.assertTrue((self.ctx.data / 'icons/hicolor/index.theme').exists())

    def test_concurrent_edit_aborts_before_any_change(self):
        plan = self.plan()
        (self.shell / 'Shell.qml').write_text('// changed\n')
        with self.assertRaises(core.RepairError):
            core.apply_plan(self.ctx, plan)
        self.assertFalse((self.ctx.data / 'icons/hicolor/index.theme').exists())

    def test_write_failure_rolls_back_prior_writes(self):
        plan = self.plan()
        real_write = core.atomic_write
        failed = False
        def fail_once(path, data, mode=0o644):
            nonlocal failed
            if path == self.shell / 'Shell.qml' and not failed:
                failed = True
                raise OSError('injected disk error')
            return real_write(path, data, mode)
        with patch.object(core, 'atomic_write', side_effect=fail_once):
            with self.assertRaises(OSError):
                core.apply_plan(self.ctx, plan)
        self.assertFalse((self.ctx.data / 'icons/hicolor/index.theme').exists())
        self.assertEqual(self.plan().changes, plan.changes)

    def test_symlinked_qml_remains_a_symlink(self):
        path = self.shell / 'dock/DockPickerRow.qml'
        real = self.home / 'linked.qml'
        path.rename(real)
        path.symlink_to(real)
        core.apply_plan(self.ctx, self.plan())
        self.assertTrue(path.is_symlink())
        self.assertIn('ResolvedAppIcon {', real.read_text())
        core.restore_latest(self.ctx)
        self.assertTrue(path.is_symlink())
        self.assertEqual(real.read_text(), dock_source())

    def test_read_only_installation_reports_skips(self):
        with patch.object(core.os, 'access', return_value=False):
            plan = self.plan()
        self.assertEqual(len(plan.changes), 1)
        self.assertEqual(len(plan.warnings), 8)

    def test_no_shell_still_repairs_hicolor(self):
        import shutil
        shutil.rmtree(self.shell)
        plan = core.plan_repair(self.ctx)
        self.assertIsNone(plan.shell)
        self.assertEqual(len(plan.changes), 1)
        self.assertTrue(plan.warnings)

    def test_check_has_no_filesystem_side_effects(self):
        paths_before = sorted(self.root.rglob('*'))
        self.plan()
        self.assertEqual(paths_before, sorted(self.root.rglob('*')))
        self.assertFalse(self.ctx.state.exists())

    def test_ambiguous_qml_is_not_patched(self):
        with self.assertRaises(core.RepairError):
            core.patch_qml(dock_source() + dock_source(), False)

    def test_xdg_absolute_paths_and_relative_fallback(self):
        with patch.dict(os.environ, {'HOME': str(self.home), 'XDG_DATA_HOME': 'relative',
                                     'XDG_STATE_HOME': str(self.home / 'custom-state'),
                                     'XDG_DATA_DIRS': '/one:relative:/two'}):
            ctx = core.Context.current()
        self.assertEqual(ctx.data, self.home / '.local/share')
        self.assertEqual(ctx.state, self.home / 'custom-state/serpantinum-icon-fix')
        self.assertEqual(ctx.data_dirs[:2], [Path('/one'), Path('/two')])


if __name__ == '__main__':
    unittest.main()
