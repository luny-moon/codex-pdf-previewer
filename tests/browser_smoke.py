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
        requests = []
        try:
            with sync_playwright() as runtime:
                browser = runtime.chromium.launch()
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda request: requests.append((request.method, request.url)))
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

                    # Pick local files entirely in the browser, without uploading
                    # their bytes or accidentally downloading the server PDF.
                    local = base / 'local picked 文档.pdf'
                    local.write_bytes(sample_pdf(2))
                    server_requests = sum('/document.pdf' in url for _, url in requests)
                    with page.expect_file_chooser() as chooser:
                        page.get_by_role('button', name='打开 PDF', exact=True).click()
                    chooser.value.set_files(str(local))
                    page.get_by_text(local.name, exact=True).wait_for()
                    ready(1)
                    assert page.locator('.pdf-page').count() == 2
                    assert page.locator('body').get_attribute('data-source-kind') == 'file'
                    assert page.locator('#refresh').inner_text() == '重新选择'
                    with page.expect_download() as download:
                        page.locator('#download').click()
                    assert Path(download.value.path()).read_bytes() == local.read_bytes()
                    assert download.value.suggested_filename == local.name

                    updated = base / 'updated' / local.name
                    updated.parent.mkdir()
                    updated.write_bytes(sample_pdf(3))
                    page.locator('#page').fill('2')
                    page.locator('#page').press('Enter')
                    ready(2)
                    with page.expect_file_chooser() as chooser:
                        page.locator('#refresh').click()
                    chooser.value.set_files(str(updated))
                    page.locator('.pdf-page').nth(2).wait_for(state='attached')
                    ready(2)
                    with page.expect_download() as download:
                        page.locator('#download').click()
                    assert Path(download.value.path()).read_bytes() == updated.read_bytes()

                    invalid = base / 'invalid.pdf'
                    invalid.write_bytes(b'not a PDF')
                    old_download = page.locator('#download').get_attribute('href')
                    page.locator('#file').set_input_files(str(invalid))
                    page.locator('#status').filter(has_text='预览失败').wait_for()
                    assert page.locator('#filename').inner_text() == local.name
                    assert page.locator('.pdf-page').count() == 3
                    assert page.locator('#download').get_attribute('href') == old_download

                    last = base / 'last.pdf'
                    last.write_bytes(sample_pdf(4))
                    page.locator('#file').set_input_files(str(local))
                    page.locator('#file').set_input_files(str(last))
                    page.get_by_text(last.name, exact=True).wait_for()
                    ready(1)
                    assert page.locator('.pdf-page').count() == 4
                    assert page.locator('#page').input_value() == '1'

                    prevented = page.evaluate('''data => {
                        const transfer = new DataTransfer();
                        transfer.items.add(new File([new Uint8Array(data)], 'dropped.pdf', {type:'application/pdf'}));
                        document.dispatchEvent(new DragEvent('dragover', {bubbles:true,cancelable:true,dataTransfer:transfer}));
                        const drop = new DragEvent('drop', {bubbles:true,cancelable:true,dataTransfer:transfer});
                        document.dispatchEvent(drop);
                        return drop.defaultPrevented;
                    }''', list(sample_pdf(1)))
                    assert prevented
                    page.get_by_text('dropped.pdf', exact=True).wait_for()
                    ready(1)
                    assert page.locator('.pdf-page').count() == 1
                    assert sum('/document.pdf' in url for _, url in requests) == server_requests
                    assert all(method == 'GET' for method, _ in requests), requests

                    # A full tab reload returns to the server-selected document;
                    # picked file bytes are never persisted in browser storage.
                    page.reload()
                    page.get_by_text(document.name, exact=True).wait_for()
                    ready(1)
                    assert page.locator('.pdf-page').count() == 5
                    assert page.locator('body').get_attribute('data-source-kind') == 'server'
                    assert not errors, errors
                    output = ROOT / 'build'
                    output.mkdir(exist_ok=True)
                    page.screenshot(path=str(output / 'synthetic-preview.png'))
                    print(json.dumps({'rendered': initial, 'selected_text_characters': selected,
                                      'refresh_and_preferences': True, 'local_pick_drop_and_download': True,
                                      'invalid_file_preserves_reader': True, 'no_file_upload_requests': True,
                                      'page_errors': errors}, indent=2))
                finally:
                    browser.close()
        finally:
            cli(state, 'stop', '--all')


if __name__ == '__main__':
    main()
