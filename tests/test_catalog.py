import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from serpantinum_icon_fix.catalog import build
from serpantinum_icon_fix.core import Context


class CatalogTests(unittest.TestCase):
    def test_inheritance_aliases_and_broken_primary_icon(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ctx = Context(root, root / 'data', root / 'config', root / 'state', [root / 'system'])
            primary = ctx.data / 'icons/Custom'
            primary.mkdir(parents=True)
            (primary / 'index.theme').write_text('[Icon Theme]\nInherits=hicolor\n')
            (primary / 'demo.svg').symlink_to(primary / 'missing.svg')
            fallback = root / 'system/icons/hicolor/64x64/apps/demo.svg'
            fallback.parent.mkdir(parents=True)
            fallback.write_text('<svg/>')
            apps = ctx.data / 'applications'
            apps.mkdir()
            (apps / 'org.example.Demo.desktop').write_text(
                '[Desktop Entry]\nName=Demo\nIcon=demo\nStartupWMClass=DemoWindow\nExec=demo-bin %U\n')
            with patch('serpantinum_icon_fix.catalog.Context.current', return_value=ctx):
                result = build('Custom')
            self.assertEqual(result['icons']['demo'], [fallback.as_uri()])
            self.assertEqual(result['aliases']['org.example.demo'], 'demo')
            self.assertEqual(result['aliases']['demowindow'], 'demo')
            self.assertEqual(result['aliases']['demo-bin'], 'demo')

    def test_symlink_cycle_and_hidden_desktop_override(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ctx = Context(root, root / 'data', root / 'config', root / 'state', [root / 'system'])
            icons = ctx.data / 'icons/hicolor/64x64/apps'
            icons.mkdir(parents=True)
            (icons / 'demo.svg').write_text('<svg/>')
            (icons / 'loop').symlink_to(icons, target_is_directory=True)
            for directory, content in ((ctx.data, 'Hidden=true\n'), (root / 'system', 'Icon=demo\n')):
                apps = directory / 'applications'
                apps.mkdir(parents=True)
                (apps / 'demo.desktop').write_text('[Desktop Entry]\nName=Demo\n' + content)
            with patch('serpantinum_icon_fix.catalog.Context.current', return_value=ctx):
                result = build('hicolor')
            self.assertEqual(len(result['icons']['demo']), 1)
            self.assertNotIn('demo', result['aliases'])
