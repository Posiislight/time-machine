"""Film the real scenarios on the Maritime computer.

python scripts/film.py record NAME      records Maritime's watch page until film/NAME.stop exists
python scripts/film.py STEP             runs one step; every step logs timestamps to film/marks.jsonl
"""
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
for l in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines():
    if '=' in l and not l.lstrip().startswith('#'):
        k, v = l.split('=', 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
from live import Live
from tm import call

CID = os.environ['TM_COMPUTER']          # id of your Maritime computer
FILM = Path(os.environ.get('TM_FILM_DIR', ROOT / 'film')); FILM.mkdir(parents=True, exist_ok=True)
STATE = FILM / 'state.json'
ME = os.environ['TM_EMAIL']                # the Google account on that computer; test emails go only to you
SHEET = os.environ.get('TM_SHEET_URL', '')   # only for the spreadsheet scenario
INBOX = 'https://mail.google.com/mail/u/0/#search/label%3ATM-test+in%3Ainbox'
ARCHIVED = 'https://mail.google.com/mail/u/0/#search/label%3ATM-test+-in%3Ainbox'
WEEK = 'https://calendar.google.com/calendar/u/0/r/week/2026/11/16'


def mark(name):
    with open(FILM / 'marks.jsonl', 'a') as f:
        f.write(json.dumps({'t': time.time(), 'name': name}) + '\n')
    print('mark', name, flush=True)


def state(**kw):
    s = json.loads(STATE.read_text()) if STATE.exists() else {}
    s.update(kw); STATE.write_text(json.dumps(s)); return s


def run(actions):
    from workspace import segments
    for part in segments(actions):
        Live().batch(CID, part)


def go(url, wait=5):
    return [{'action': 'key', 'text': 'ctrl+l'}, {'action': 'type', 'text': url + '\n'}, {'action': 'wait', 'duration': wait}]


def compose(subject, body):
    return go('https://mail.google.com/mail/u/0/?view=cm&fs=1', 6) + [
        {'action': 'type', 'text': ME}, {'action': 'wait', 'duration': 1}, {'action': 'key', 'text': 'Tab'}, {'action': 'wait', 'duration': 1},
        {'action': 'key', 'text': 'Tab'}, {'action': 'type', 'text': subject}, {'action': 'key', 'text': 'Tab'},
        {'action': 'type', 'text': body}, {'action': 'wait', 'duration': 2}, {'action': 'key', 'text': 'ctrl+Return'}, {'action': 'wait', 'duration': 4}]


# -- recipes (each one undoes the other) -----------------------------------------------
def archive():
    return go(INBOX, 5) + [{'action': 'left_click', 'coordinate': [264, 239]}, {'action': 'wait', 'duration': 1},
                           {'action': 'left_click', 'coordinate': [320, 239]}, {'action': 'wait', 'duration': 3}]


def unarchive():
    return go(ARCHIVED, 5) + [{'action': 'left_click', 'coordinate': [264, 239]}, {'action': 'wait', 'duration': 1},
                              {'action': 'left_click', 'coordinate': [500, 239]}, {'action': 'wait', 'duration': 2}] + go(INBOX, 4)


def fill(word):
    return go(SHEET, 7) + [{'action': 'key', 'text': 'Escape'}, {'action': 'left_click', 'coordinate': [60, 223]},
                           {'action': 'type', 'text': 'C2\n'}, {'action': 'wait', 'duration': 1},
                           {'action': 'type', 'text': (word + '\n') * 50}, {'action': 'wait', 'duration': 2},
                           {'action': 'key', 'text': 'ctrl+Home'}, {'action': 'wait', 'duration': 2}]


EVENTS = [('TM-test+Team+sync', '20261116T100000/20261116T103000', 383),
          ('TM-test+Design+review', '20261116T110000/20261116T113000', 421),
          ('TM-test+Client+call', '20261116T140000/20261116T143000', 533)]


def place(t, d):
    return go('https://calendar.google.com/calendar/u/0/r/eventedit?text=%s&dates=%s' % (t, d), 6) + [
        {'action': 'left_click', 'coordinate': [699, 141]}, {'action': 'wait', 'duration': 4}]


def unplace():
    a = []
    for _ in EVENTS:   # Calendar search lists the next test meeting first, whatever the scroll position
        a += go('https://calendar.google.com/calendar/u/0/r/search?q=TM-test', 4) + [
            {'action': 'left_click', 'coordinate': [640, 186]}, {'action': 'wait', 'duration': 2}, {'action': 'key', 'text': 'Delete'}, {'action': 'wait', 'duration': 2}]
    return a + go(WEEK, 5)


def effect(sid, key):
    return {e['operation_key']: e for e in call('GET', '/api/session?id=' + sid)['effects']}[key]['id']


def do(sid, description, kind, key, undo=None):
    r = call('POST', '/api/session/do', {'session': sid, 'description': description, 'kind': kind, 'key': key, 'actions': None, 'undo': undo})
    assert 'id' in r, r


def stall(sid, label, step):
    call('POST', '/api/session/update', {'session': sid, 'resources': {'agent': {'recovery': 'logical', 'state': {'step': step, 'computer': CID}}}})
    call('POST', '/api/session/checkpoint', {'session': sid, 'label': label})


def reconcile(sid, key, evidence):
    print(call('POST', '/api/session/reconcile', {'session': sid, 'effect': effect(sid, key), 'status': 'completed', 'evidence': evidence}))


# -- steps ---------------------------------------------------------------------------
def record(name):
    from playwright.sync_api import sync_playwright
    url = Live().request('/api/v1/computers/%s/viewer' % CID, {'mode': 'watch', 'ttlS': 3600, 'reason': 'Record the walkthrough'})['url']
    stop = FILM / (name + '.stop'); stop.unlink(missing_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={'width': 1600, 'height': 1000}, record_video_dir=str(FILM / name), record_video_size={'width': 1600, 'height': 1000})
        t0 = time.time(); pg = ctx.new_page(); pg.goto(url)
        (FILM / (name + '.json')).write_text(json.dumps({'t0': t0}))
        print('recording', flush=True)
        while not stop.exists() and time.time() - t0 < 3300:
            pg.wait_for_timeout(500)
        ctx.close(); b.close()
    print('saved', flush=True)


def tm_rewind(sid, title, name):
    """Rewind through the Time Machine screen while it is recorded."""
    from playwright.sync_api import sync_playwright, expect
    expect.set_options(timeout=240_000)
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={'width': 1600, 'height': 900}, record_video_dir=str(FILM / name), record_video_size={'width': 1600, 'height': 900})
        t0 = time.time(); pg = ctx.new_page(); pg.goto('http://127.0.0.1:8765/#s=' + sid); pg.reload()
        (FILM / (name + '.json')).write_text(json.dumps({'t0': t0}))
        expect(pg.locator('#title')).to_have_text(title); pg.wait_for_timeout(2500); mark(name + ':timeline')
        pg.locator('.snapbtn', has_text='Before the task').click()
        expect(pg.locator('.block.comes')).to_be_visible(); mark(name + ':preview'); pg.wait_for_timeout(4000)
        pg.check('#ack'); pg.wait_for_timeout(1000); mark(name + ':click')
        pg.click('text=Rewind to here')
        expect(pg.locator('#kicker')).to_have_text('Recovered branch'); mark(name + ':recovered'); pg.wait_for_timeout(4000)
        ctx.close(); b.close()


def step(name):
    s = state()
    if name == 'inbox1':
        run(go(INBOX, 5)); mark('inbox:before'); time.sleep(3)
        sid = call('POST', '/api/session/task', {'title': 'Tidy promotional emails', 'computer': CID})['id']; state(inbox=sid)
        do(sid, 'Archived 10 promotional emails', 'change', 'archive-10', unarchive())
        mark('inbox:archive'); run(archive()); mark('inbox:archived'); time.sleep(3)
        do(sid, 'Sent 2 follow-up emails', 'message', 'followups-2')
        mark('inbox:send1'); run(compose('Follow-up 1 of 2 (Time Machine test)', 'Thanks for trying the product. This is test follow-up 1 of 2.'))
        mark('inbox:send2'); run(compose('Follow-up 2 of 2 (Time Machine test)', 'Thanks for trying the product. This is test follow-up 2 of 2.'))
        mark('inbox:sent'); run(go(INBOX, 4)); mark('inbox:empty'); time.sleep(3)
    elif name == 'inbox2':
        sid = s['inbox']
        reconcile(sid, 'archive-10', 'Gmail lists 0 TM-test emails in the inbox and 10 archived.')
        reconcile(sid, 'followups-2', 'Gmail Sent holds both follow-ups, addressed only to the account owner.')
        call('POST', '/api/session/checkpoint', {'session': sid, 'label': 'After archiving and follow-ups'})
        stall(sid, 'Lost connection', 'Connection lost before emptying the trash')
    elif name == 'inbox3':
        run(go(INBOX, 4)); mark('inbox:rewind_start')
        tm_rewind(s['inbox'], 'Tidy promotional emails', 'inbox_tm'); mark('inbox:restored')
        run(go('https://mail.google.com/mail/u/0/#search/in%3Asent+%22Time+Machine+test%22', 5)); mark('inbox:sent_view'); time.sleep(4)
    elif name == 'sheet1':
        run(go(SHEET, 7) + [{'action': 'key', 'text': 'Escape'}]); mark('sheet:before'); time.sleep(3)
        sid = call('POST', '/api/session/task', {'title': 'Update customer statuses', 'computer': CID})['id']; state(sheet=sid)
        do(sid, 'Changed 50 customer rows from Trial to Active', 'change', 'rows-50', fill('Trial'))
        mark('sheet:fill'); run(fill('Active')); mark('sheet:filled'); time.sleep(3)
        do(sid, 'Emailed 2 account owners about the change', 'message', 'owners-2')
        mark('sheet:send1'); run(compose('Account update 1 of 2 (Time Machine test)', 'Your account is now Active. This is test message 1 of 2.'))
        mark('sheet:send2'); run(compose('Account update 2 of 2 (Time Machine test)', 'Your account is now Active. This is test message 2 of 2.'))
        mark('sheet:sent'); run(go(SHEET, 7) + [{'action': 'key', 'text': 'Escape'}]); mark('sheet:active'); time.sleep(3)
    elif name == 'sheet2':
        sid = s['sheet']
        reconcile(sid, 'rows-50', 'Google Sheets lists Active in all 50 rows of column C.')
        reconcile(sid, 'owners-2', 'Gmail Sent holds both messages, addressed only to the account owner.')
        call('POST', '/api/session/checkpoint', {'session': sid, 'label': 'After updating 50 rows'})
        stall(sid, 'Agent crashed', 'Crashed while deleting the old tab')
    elif name == 'sheet3':
        mark('sheet:rewind_start')
        tm_rewind(s['sheet'], 'Update customer statuses', 'sheet_tm'); mark('sheet:restored'); time.sleep(4)
        run(go('https://mail.google.com/mail/u/0/#search/in%3Asent+%22Account+update%22', 5)); mark('sheet:sent_view'); time.sleep(4)
    elif name == 'cal1':
        run(go(WEEK, 6)); mark('cal:before'); time.sleep(3)
        sid = call('POST', '/api/session/task', {'title': "Reshuffle the week's meetings", 'computer': CID})['id']; state(cal=sid)
        do(sid, 'Placed 3 meetings on the calendar', 'change', 'meetings-3', unplace())
        for i, (t, d, _) in enumerate(EVENTS):
            mark('cal:place%d' % i); run(place(t, d))
        run(go(WEEK, 6)); mark('cal:placed'); time.sleep(3)
        do(sid, 'Emailed the attendee about the new times', 'message', 'notify-1')
        mark('cal:send'); run(compose('New meeting times (Time Machine test)', 'Three meetings moved to Monday 16 November. This is a test message.'))
        mark('cal:sent'); run(go(WEEK, 6)); mark('cal:full'); time.sleep(3)
    elif name == 'cal2':
        sid = s['cal']
        reconcile(sid, 'meetings-3', 'Google Calendar week of Nov 16 shows Team sync, Design review and Client call.')
        reconcile(sid, 'notify-1', 'Gmail Sent holds the message, addressed only to the account owner.')
        call('POST', '/api/session/checkpoint', {'session': sid, 'label': 'After placing 3 meetings'})
        stall(sid, 'Agent stalled', 'Stalled while clearing Friday')
    elif name == 'cal3':
        mark('cal:rewind_start')
        tm_rewind(s['cal'], "Reshuffle the week's meetings", 'cal_tm'); mark('cal:restored'); time.sleep(4)
        run(go('https://mail.google.com/mail/u/0/#search/in%3Asent+%22New+meeting+times%22', 5)); mark('cal:sent_view'); time.sleep(4)


if __name__ == '__main__':
    record(sys.argv[2]) if sys.argv[1] == 'record' else step(sys.argv[1])
