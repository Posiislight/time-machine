"""Record a walkthrough of Time Machine working on a real Maritime machine.

Starts its own server on a fresh data folder, drives the real UI with Playwright, then removes
every machine and snapshot it created. Uses a little plan credit.
Run: python scripts/record_walkthrough.py   (needs MARITIME_API_KEY in .env, and `playwright install chromium`)
"""
import os, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
env_file = ROOT / '.env'
if env_file.exists():
    for line in env_file.read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
from sandboxes import Sandboxes

expect.set_options(timeout=90_000)
URL = 'http://127.0.0.1:8765/'
RELEASE = 'pricing-v1'
OUT = ROOT / 'walkthrough'


def cleanup():
    m = Sandboxes()
    for box in m._api('GET', '/v1/sandboxes').get('data', []):
        if box.get('name', '').startswith('tm-') and box.get('state') != 'ended':
            try: m.kill(box['id']); print('ended machine', box['id'])
            except Exception as e: print('could not end', box['id'], e)
    for snap in m.snapshots():
        if snap['name'].startswith('tm-') or snap['name'] == RELEASE:
            try: m.delete_snapshot(snap['name']); print('deleted snapshot', snap['name'])
            except Exception as e: print('could not delete', snap['name'], e)


def main():
    data = tempfile.mkdtemp(prefix='tm-data-')
    cleanup()
    server = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT,
                              env={**os.environ, 'NO_BROWSER': '1', 'TIME_MACHINE_DATA': data})
    time.sleep(2)
    shutil.rmtree(OUT, ignore_errors=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={'width': 1280, 'height': 720}, record_video_dir=str(OUT),
                                      record_video_size={'width': 1280, 'height': 720})
            page = ctx.new_page(); page.set_default_timeout(90_000)
            shot = lambda n: page.screenshot(path=str(OUT / (n + '.png')))
            pause = lambda s=1.3: page.wait_for_timeout(int(s * 1000))
            def run(cmd):
                page.fill('#cmd', ''); page.type('#cmd', cmd, delay=45); pause(.6)
                page.click('#runBtn'); expect(page.locator('#runBtn')).to_have_text('Run'); expect(page.locator('#output')).to_be_visible(); pause(1.6)

            page.goto(URL); pause(2.2)
            page.type('#sessionName', 'Build the pricing page', delay=60); pause(.8)
            page.click('#startBtn')
            expect(page.locator('#badge')).to_contain_text('Machine sbx-'); pause(1.6)

            run('echo "<h1>Pricing</h1><p>Free, Pro, Team</p>" > index.html && cat index.html')
            page.type('#releaseName', RELEASE, delay=60); pause(.6)
            page.click('#publishBtn'); expect(page.locator('#notice')).to_contain_text('Published'); pause(2.2)
            run('rm index.html && ls -la')   # the agent goes wrong
            pause(1.5)

            shot('2-timeline')
            page.locator('.snapbtn', has_text='After: echo').click()
            expect(page.locator('.block.comes')).to_be_visible(); pause(1.5); shot('3-preview')
            page.locator('#previewPanel').scroll_into_view_if_needed(); pause(3.5)
            page.check('#ack'); pause(1)
            page.click('text=Rewind to here')
            expect(page.locator('#kicker')).to_have_text('Recovered branch'); pause(2.5)

            run('cat index.html')            # the file is back on the new machine
            expect(page.locator('#output')).to_contain_text('Pricing'); shot('4-restored'); pause(2)
            page.type('#releaseName', RELEASE, delay=60); pause(.5)
            page.click('#publishBtn'); expect(page.locator('#notice')).to_contain_text('already recorded'); shot('5-refused'); pause(3.5)
            ctx.close(); browser.close()
        video = next(OUT.glob('*.webm')); video.rename(OUT / 'time-machine-walkthrough.webm')
        print('video:', OUT / 'time-machine-walkthrough.webm')
    finally:
        server.terminate()
        cleanup()
        shutil.rmtree(data, ignore_errors=True)


if __name__ == '__main__':
    main()
