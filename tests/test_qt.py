"""Optional integration test using Qt's real theme loader (not a mock)."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from serpantinum_icon_fix.core import Context, hicolor_index


@unittest.skipUnless(importlib.util.find_spec('PySide6'), 'optional PySide6 is not installed')
class QtIntegrationTests(unittest.TestCase):
    def test_generated_index_loads_image_from_another_icon_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = Context(root / 'home', root / 'data', root / 'config', root / 'state', [root / 'system'])
            image = root / 'system/icons/hicolor/80x80/apps/serpantinum-fixture.svg'
            image.parent.mkdir(parents=True)
            image.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80">'
                             '<rect width="80" height="80" fill="#2288bb"/></svg>')
            index = root / 'data/icons/hicolor/index.theme'
            index.parent.mkdir(parents=True)
            index.write_bytes(hicolor_index(ctx))
            code = '''
import sys
from PySide6.QtGui import QGuiApplication, QIcon
app = QGuiApplication([])
QIcon.setThemeSearchPaths(sys.argv[1:])
QIcon.setThemeName('hicolor')
assert QIcon.hasThemeIcon('serpantinum-fixture')
assert not QIcon.fromTheme('serpantinum-fixture').pixmap(64, 64).isNull()
assert not QIcon.hasThemeIcon('serpantinum-missing-fixture')
print('Qt loaded the real icon through the generated user index')
'''
            env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
            result = subprocess.run([sys.executable, '-c', code, str(root / 'data/icons'), str(root / 'system/icons')],
                                    env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
