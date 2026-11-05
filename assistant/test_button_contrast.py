"""Browser regression checks for secondary and primary button contrast."""
import html
import json
import pathlib
import re
import subprocess
import tempfile
import unittest


class ButtonContrastTests(unittest.TestCase):
    def test_hovered_buttons_are_readable_in_both_themes(self):
        static = pathlib.Path(__file__).parent / 'static'
        # Replace :hover with an equally specific class so headless Chromium can
        # exercise the exact cascade deterministically without mouse positioning.
        css = '\n'.join((static / name).read_text() for name in
                        ('static.css', 'design.css', 'swiss.css')).replace(':hover', '.test-hover')
        document = '''<!doctype html><style>CSS</style>
          <div class="account-nav"><button id="account">Account</button></div>
          <header class="site-header"><nav><button id="staff">Staff</button></nav></header>
          <button id="chat-new">New</button>
          <div class="theme-switch"><button id="theme" aria-pressed="true">Theme</button></div>
          <button id="primary">Primary</button><pre id="result"></pre>
          <script>
          const luminance = c => {
            const rgb = c.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => {
              v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;
            });
            return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
          };
          const out = {};
          for (const theme of ['light', 'dark']) {
            document.documentElement.dataset.theme = theme;
            out[theme] = {};
            for (const id of ['account', 'staff', 'chat-new', 'theme', 'primary']) {
              const el = document.getElementById(id); el.classList.add('test-hover');
              const s = getComputedStyle(el), a = luminance(s.color), b = luminance(s.backgroundColor);
              out[theme][id] = {color: s.color, background: s.backgroundColor,
                contrast: (Math.max(a,b)+.05)/(Math.min(a,b)+.05)};
              el.classList.remove('test-hover');
            }
          }
          document.getElementById('result').textContent = JSON.stringify(out);
          </script>'''.replace('CSS', css)
        with tempfile.TemporaryDirectory() as directory:
            page = pathlib.Path(directory) / 'test.html'
            page.write_text(document)
            result = subprocess.run(['chromium', '--headless', '--no-sandbox', '--disable-gpu',
                                     '--dump-dom', page.as_uri()], capture_output=True,
                                    text=True, check=True, timeout=30)
        match = re.search(r'<pre id="result">(.*?)</pre>', result.stdout, re.S)
        self.assertIsNotNone(match, result.stderr)
        measurements = json.loads(html.unescape(match.group(1)))
        for theme, buttons in measurements.items():
            for name, values in buttons.items():
                with self.subTest(theme=theme, button=name):
                    self.assertGreaterEqual(values['contrast'], 4.5, values)


if __name__ == '__main__':
    unittest.main()
