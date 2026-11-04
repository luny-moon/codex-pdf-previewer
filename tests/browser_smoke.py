"""Render only generated sample data; no user document is read."""
import json
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
from support import ROOT, cli, sample_pdf


def main():
    with tempfile.TemporaryDirectory(prefix='hd-pdf-browser-') as temporary:
        base = Path(temporary)
        document = base / 'sample 文档 with spaces.pdf'
        document.write_bytes(sample_pdf())
        state = base / 'state'
        session = cli(state, 'open', document)
        errors = []
        try:
            with sync_playwright() as runtime:
                browser = runtime.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(session['url'])

                    def ready(number):
                        page.locator(f'.pdf-page[data-page="{number}"][data-render-state="ready"]').wait_for(timeout=45000)

                    ready(1)
                    initial = page.evaluate('''() => {
                        const canvas = document.querySelector('.pdf-page canvas');
                        return {zoom: document.querySelector('#zoom').value,
                            quality: document.querySelector('#quality').value,
                            pages: document.querySelectorAll('.pdf-page').length,
                            width: canvas.width, height: canvas.height,
                            sampling: canvas.width / parseFloat(canvas.style.width)};
                    }''')
                    assert initial['zoom'] == '1.5' and initial['quality'] == '3', initial
                    assert initial['pages'] == 5 and abs(initial['sampling'] - 3) < 0.01, initial
                    page.locator('#page').fill('3')
                    page.locator('#page').press('Enter')
                    ready(3)
                    page.locator('#zoom').select_option('fit')
                    ready(3)
                    page.locator('#quality').select_option('2')
                    ready(3)
                    selected = page.evaluate('''() => {
                        const record = document.querySelector('.pdf-page[data-page="3"]');
                        const selection = window.getSelection();
                        selection.selectAllChildren(record.querySelector('.textLayer'));
                        const count = selection.toString().length;
                        selection.removeAllRanges();
                        return count;
                    }''')
                    assert selected > 20, selected
                    page.locator('#refresh').click()
                    ready(3)
                    assert page.locator('#page').input_value() == '3'
                    page.reload()
                    ready(1)
                    assert page.locator('#zoom').input_value() == 'fit'
                    assert page.locator('#quality').input_value() == '2'
                    assert not errors, errors
                    output = ROOT / 'build'
                    output.mkdir(exist_ok=True)
                    page.screenshot(path=str(output / 'synthetic-preview.png'))
                    print(json.dumps({'rendered': initial, 'selected_text_characters': selected,
                                      'refresh_and_preferences': True, 'page_errors': errors}, indent=2))
                finally:
                    browser.close()
        finally:
            cli(state, 'stop', '--all')


if __name__ == '__main__':
    main()
