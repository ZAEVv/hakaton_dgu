"""Regression checks for the shared theme control's rendered states."""
import html
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


class ThemeLayoutTests(unittest.TestCase):
    def test_selected_control_remains_distinct_on_hover(self):
        static = Path(__file__).parent / 'static'
        css = '\n'.join((static / name).read_text() for name in
                        ('static.css', 'design.css', 'swiss.css', 'college.css')).replace(':hover', '.test-hover')
        page = '''<!doctype html><style>CSS</style><header class="site-header">
        <div class="theme-switch"><button aria-pressed="true" class="test-hover">Светлая</button>
        <button aria-pressed="false" class="test-hover">Тёмная</button></div></header><pre id="result"></pre>
        <script>const out={}; for(const theme of ['light','dark']) {
          document.documentElement.dataset.theme=theme;
          const b=[...document.querySelectorAll('button')].map(e=>getComputedStyle(e));
          out[theme]=b.map(s=>({bg:s.backgroundColor,color:s.color}));
        } document.querySelector('#result').textContent=JSON.stringify(out);</script>'''.replace('CSS', css)
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'page.html'
            file.write_text(page)
            result = subprocess.run(['chromium', '--headless', '--no-sandbox', '--disable-gpu', '--dump-dom', file.as_uri()], capture_output=True, text=True, check=True, timeout=30)
        match = re.search(r'<pre id="result">(.*?)</pre>', result.stdout, re.S)
        self.assertIsNotNone(match, result.stderr)
        for theme, states in json.loads(html.unescape(match.group(1))).items():
            with self.subTest(theme=theme):
                self.assertNotEqual(states[0]['bg'], states[1]['bg'], states)


if __name__ == '__main__':
    unittest.main()
