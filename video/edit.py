"""Cut the launch video from the real screen recordings: music + on-screen text, no voice, no sound effects.

python video/edit.py            plan + frames + music + render
python video/edit.py --plan     timings only
Drop your own track at video/music.mp3 (or .wav) to use it instead of the composed bed.
"""
import json, shutil, subprocess, sys, wave
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
from footage import FF, at, video

HERE = Path(__file__).resolve().parent
B = HERE / 'build2'; B.mkdir(exist_ok=True)
FPS, SR = 30, 44100
BPM = 100
BEAT = 60.0 / BPM
SCREEN_CROP = (29, 112, 1542, 853)          # drops the window title, tabs and taskbar (they show the email address)


def S(rec, mark, plus=0.0):
    return round(at(rec, mark, plus), 2)


# Each shot: length in beats, what is seen, and the text on screen.
# caption: a string, or [[progress 0..1, text], ...]. <b>..</b> is the stressed part.
# Zoom keys: [progress 0..1, scale, focus x 0..1, focus y 0..1]
SHOTS = [
    dict(id='hook', kind='card', beats=7, lines=[.2, 2.1]),
    dict(id='problem', kind='card', beats=7, lines=[.2]),
    dict(id='intro', kind='card', beats=8, lines=[.2, 2.4]),

    # --- the product: start a session ---
    dict(id='home', kind='clip', beats=5, rec='inbox_tm', a=0, b=.1, tm=True, chip='Start a session',
         caption='Time Machine <b>snapshots every step</b> the agent takes',
         zoom=[[0, 1, .5, .5], [1, 1.5, .36, .38]]),

    # --- example 1: Gmail ---
    dict(id='g1', kind='clip', beats=4, rec='inbox_screen', a=S('inbox_screen', 'inbox:before', .3), b=S('inbox_screen', 'inbox:before', 3.2),
         chip='Gmail', caption='A real Gmail inbox, on a <b>Maritime computer</b>',
         zoom=[[0, 1, .5, .5], [1, 1.25, .62, .45]]),
    dict(id='g2', kind='clip', beats=5, rec='inbox_screen', a=S('inbox_screen', 'inbox:archive', .5), b=S('inbox_screen', 'inbox:archived', .8),
         chip='Gmail', caption='The agent <b>archives 10</b> promotional emails',
         zoom=[[0, 1.25, .62, .45], [.6, 1.25, .62, .45], [1, 1.35, .3, .86]]),
    dict(id='g3', kind='clip', beats=5, rec='inbox_screen', a=S('inbox_screen', 'inbox:send1', 13), b=S('inbox_screen', 'inbox:send2', 2),
         chip='Gmail', caption='…and <b>sends 2 follow-up emails</b>',
         zoom=[[0, 1.6, .3, .2], [1, 1.6, .3, .2]], blur=[.02, .1, .4, .17]),
    dict(id='g4', kind='clip', beats=5, rec='inbox_screen', a=S('inbox_screen', 'inbox:empty', .5), b=S('inbox_screen', 'inbox:empty', 2.5),
         chip='Gmail', caption='Then the agent <b>fails halfway</b> through the job',
         overlay='crash', crash='Agent lost its connection', crash_at=.3,
         zoom=[[0, 1, .5, .5], [1, 1.05, .5, .5]]),

    # --- the product: timeline, preview, rewind ---
    dict(id='t1a', kind='clip', beats=5, rec='inbox_tm', a=S('inbox_tm', 'inbox_tm:preview', 0), b=S('inbox_tm', 'inbox_tm:preview', 2.6), tm=True, chip='Timeline',
         caption=[[0, 'Every step the agent took is <b>saved on a timeline</b>'], [.5, 'Pick any moment to <b>preview the rewind</b>']],
         zoom=[[0, 1.5, .5, .43], [.45, 1.5, .5, .43], [.7, 1.9, .7, .3], [1, 1.9, .7, .3]]),
    dict(id='t1b', kind='clip', beats=7, rec='inbox_tm', a=S('inbox_tm', 'inbox_tm:preview', 2.6), b=S('inbox_tm', 'inbox_tm:click', .5), tm=True, chip='Rewind preview',
         caption=[[0, '<b>Comes back:</b> the 10 archived emails'], [.33, '<b>Stays:</b> the 2 emails already sent. They can’t be unsent'], [.7, 'Confirm, then <b>rewind</b>']],
         click=[.6, .504, .93],
         zoom=[[0, 1.9, .7, .27], [.33, 1.9, .7, .37], [.6, 1.9, .7, .45], [1, 1.9, .7, .45]]),
    dict(id='r1', kind='clip', beats=7, rec='inbox_tm', a=S('inbox_tm', 'inbox_tm:recovered', .2), b=S('inbox_tm', 'inbox_tm:recovered', 3.2), tm=True, chip='Receipt',
         caption=[[0, 'The agent continues from a <b>recovered branch</b>'], [.45, '<b>Archive: undone.</b> Follow-ups: <b>kept</b>']],
         zoom=[[0, 1.35, .45, .3], [.4, 1.35, .45, .3], [.6, 1.8, .43, .52], [1, 1.8, .43, .52]]),
    dict(id='g5', kind='clip', beats=6, rec='inbox_screen', a=S('inbox_screen', 'inbox_tm:click', .3), b=S('inbox_screen', 'inbox:restored', 1.0),
         chip='Gmail', caption='One click. <b>All 10 emails are back</b> in the inbox',
         zoom=[[0, 1, .5, .5], [.55, 1, .5, .5], [.7, 1.4, .2, .86], [.85, 1.4, .2, .86], [1, 1.1, .55, .5]]),
    dict(id='g6', kind='clip', beats=5, rec='inbox_screen', a=S('inbox_screen', 'inbox:sent_view', .3), b=S('inbox_screen', 'inbox:sent_view', 3.5),
         chip='Gmail', caption='The follow-ups <b>stay sent</b>, and are never sent twice',
         zoom=[[0, 1, .5, .5], [1, 1.6, .55, .35]]),

    # --- example 2: Calendar ---
    dict(id='c1', kind='clip', beats=8, rec='cal_screen', a=S('cal_screen', 'cal:before', .5), b=S('cal_screen', 'cal:placed', 3.5),
         chip='Google Calendar', caption=[[0, 'In <b>Google Calendar</b>, the agent books 3 meetings'], [.7, 'But now you want to <b>change what it did</b>']],
         zoom=[[0, 1, .5, .5], [.8, 1, .5, .5], [1, 1.4, .37, .5]]),
    dict(id='tc', kind='clip', beats=8, rec='cal_tm', a=S('cal_tm', 'cal_tm:preview', 0), b=S('cal_tm', 'cal_tm:click', .5), tm=True, chip='Rewind preview',
         caption=[[0, 'Same Time Machine, <b>any app</b>'], [.3, '<b>Comes back:</b> the 3 meetings. <b>Stays:</b> the email it sent'], [.78, 'Just click <b>Rewind</b>']],
         click=[.6, .504, .95],
         zoom=[[0, 1.5, .5, .43], [.3, 1.9, .7, .27], [.6, 1.9, .7, .4], [1, 1.9, .7, .45]]),
    dict(id='c2', kind='clip', beats=7, rec='cal_screen', a=S('cal_screen', 'cal_tm:click', .3), b=S('cal_screen', 'cal:restored', .2),
         chip='Google Calendar', caption=[[0, 'Rewind <b>removes all 3 meetings</b>'], [.55, 'The notification it emailed <b>stays sent</b>']],
         zoom=[[0, 1.4, .45, .25], [1, 1.4, .45, .25]]),
    dict(id='rc', kind='clip', beats=6, rec='cal_tm', a=S('cal_tm', 'cal_tm:recovered', .2), b=S('cal_tm', 'cal_tm:recovered', 3.2), tm=True, chip='Receipt',
         caption=[[0, 'Meetings: <b>undone</b>'], [.5, 'Email: <b>kept</b>. Everything stays on the record']],
         zoom=[[0, 1.6, .45, .42], [1, 1.6, .45, .42]]),

    dict(id='pillars', kind='card', beats=8, lines=[.2, 1.0]),
    dict(id='close', kind='card', beats=9, lines=[.2, 1.4]),
]


def plan():
    t, edl = 0.0, []
    for s in SHOTS:
        dur = round(s['beats'] * BEAT, 3)
        e = dict(s, start=round(t, 3), dur=dur)
        if s['kind'] == 'clip':
            e['speed'] = round(min(max((s['b'] - s['a']) / dur, 1.0), 24.0), 3)
        edl.append(e); t += dur
    return edl, round(t, 3)


def extract(e):
    d = B / 'shots' / e['id']
    stamp = d / 'stamp.json'; want = json.dumps([e['rec'], e['a'], e['b'], e['speed'], e['dur'], 'nodark'])
    if stamp.exists() and stamp.read_text() == want:
        return len(list(d.glob('*.jpg')))
    shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
    vf = 'trim=start=%s:end=%s,setpts=(PTS-STARTPTS)/%s,fps=%d' % (e['a'], e['b'], e['speed'], FPS)
    if not e.get('tm'):
        vf += ',crop=%d:%d:%d:%d' % (SCREEN_CROP[2], SCREEN_CROP[3], SCREEN_CROP[0], SCREEN_CROP[1])
    vf += ',scale=1920:-2'
    subprocess.run([FF, '-y', '-v', 'error', '-i', str(video(e['rec'])),
                    '-vf', vf, '-q:v', '3', str(d / '%05d.jpg')], check=True)
    if not e.get('tm'):   # drop frames where Maritime's viewer was reconnecting (a dark screen): a jump cut
        from PIL import Image
        keep = [f for f in sorted(d.glob('*.jpg')) if np.asarray(Image.open(f).convert('L').resize((32, 18))).mean() >= 60]
        for f in sorted(d.glob('*.jpg')):
            if f not in keep: f.unlink()
        for i, f in enumerate(keep, 1):
            f.rename(d / ('%05d.jpg' % i))
    stamp.write_text(want)
    return len(list(d.glob('*.jpg')))


# ---------------- music: a soft, warm bed. No noise, no whooshes, no hits. ----------------
def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def tone(freq, dur, vol, decay=3.0, attack=.01, harm=(1.0, .35, .12)):
    n = int(dur * SR); t = np.arange(n) / SR
    y = sum(h * np.sin(2 * np.pi * freq * (k + 1) * t) for k, h in enumerate(harm))
    env = np.minimum(t / attack, 1) * np.exp(-t * decay)
    return (y * env * vol).astype(np.float32)


CHORDS = [  # (bass, chord tones) for C maj7, A min7, F maj7, G6
    (36, [60, 64, 67, 71]), (33, [57, 60, 64, 67]), (41, [57, 60, 65, 69]), (43, [59, 62, 67, 71]),
]


def compose(total):
    n = int((total + 3) * SR); x = np.zeros(n, np.float32)
    def put(t, y):
        i = int(t * SR)
        if i < n: y = y[:n - i]; x[i:i + len(y)] += y
    bar = 4 * BEAT; bars = int(total / bar) + 2
    for b in range(bars):
        t0 = b * bar; bass, chord = CHORDS[b % 4]
        for m in chord[:3]:                                    # warm pad
            ln = bar + .6; tt = np.arange(int(ln * SR)) / SR
            env = np.minimum(tt / .5, 1) * np.minimum((ln - tt) / .6, 1)
            put(t0, (np.sin(2 * np.pi * hz(m - 12) * tt) * env * .035).astype(np.float32))
        put(t0, tone(hz(bass), bar * .9, .16, decay=1.1, harm=(1, .25)))              # bass on 1
        put(t0 + 2 * BEAT, tone(hz(bass), bar * .45, .11, decay=1.6, harm=(1, .25)))   # and 3
        if b >= 1:
            for beat in (0, 2):                                # very soft kick
                tt = np.arange(int(.3 * SR)) / SR
                put(t0 + beat * BEAT, (np.sin(2 * np.pi * (52 + 40 * np.exp(-tt * 25)) * tt) * np.exp(-tt * 11) * .13).astype(np.float32))
        seq = [0, 1, 2, 3, 2, 1, 2, 3] if b % 2 == 0 else [0, 2, 1, 3, 2, 3, 1, 2]
        for k in range(8):                                     # electric-piano arpeggio, eighth notes
            m = chord[seq[k]] + (12 if k in (3, 7) and b % 4 == 3 else 0)
            put(t0 + k * BEAT / 2, tone(hz(m), 1.4, .09 if b >= 1 else .06, decay=3.4))
    x = x[:int((total + .2) * SR)]
    k = int(.012 * SR); r = np.concatenate([np.zeros(k, np.float32), x])[:len(x)]
    return np.stack([x, .8 * x + .35 * r]), x                  # (stereo with a touch of width)


def music(total):
    n = int((total + .2) * SR)
    mine = [p for p in (HERE / 'music.mp3', HERE / 'music.wav') if p.exists()]
    if mine:
        raw = subprocess.run([FF, '-v', 'error', '-i', str(mine[0]), '-f', 'f32le', '-ac', '2', '-ar', str(SR), '-'], capture_output=True, check=True).stdout
        st = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).T.copy()
        st = st[:, :n] if st.shape[1] >= n else np.pad(st, ((0, 0), (0, n - st.shape[1])))
        print('music: using', mine[0].name)
    else:
        st, _ = compose(total); st = st[:, :n]
    t = np.arange(st.shape[1]) / SR
    st = st * np.minimum(t / .8, 1) * np.clip((total + .2 - t) / 2.2, 0, 1)
    st = st / max(np.max(np.abs(st)), 1e-6) * .8
    with wave.open(str(B / 'audio.wav'), 'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((st.T * 32767).astype(np.int16).tobytes())


def render(total):
    from playwright.sync_api import sync_playwright
    fr = B / 'frames'; shutil.rmtree(fr, ignore_errors=True); fr.mkdir()
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={'width': 1920, 'height': 1080})
        pg.goto((HERE / 'edit.html').as_uri()); pg.wait_for_function('window.ready === true')
        n = int(total * FPS)
        for i in range(n):
            pg.evaluate('t => window.render(t)', i / FPS)
            pg.screenshot(path=str(fr / ('%05d.jpg' % i)), type='jpeg', quality=92)
            if i % 300 == 0: print('frame', i, '/', n, flush=True)
        b.close()
    dst = HERE.parent / 'walkthrough' / 'time-machine-launch.mp4'
    subprocess.run([FF, '-y', '-v', 'error', '-framerate', str(FPS), '-i', str(fr / '%05d.jpg'), '-i', str(B / 'audio.wav'),
                    '-vf', 'scale=in_range=full:out_range=tv,format=yuv420p', '-c:v', 'libx264', '-crf', '18', '-preset', 'slow', '-color_range', 'tv', '-c:a', 'aac', '-b:a', '192k',
                    '-shortest', '-movflags', '+faststart', str(dst)], check=True)
    print('wrote', dst)


if __name__ == '__main__':
    edl, total = plan()
    for e in edl:
        print('%-8s %6.2f %5.2f %s' % (e['id'], e['start'], e['dur'], ('speed %.1fx' % e['speed']) if 'speed' in e else ''))
    print('total', total)
    if '--plan' in sys.argv: sys.exit()
    for e in edl:
        if e['kind'] == 'clip':
            e['frames'] = extract(e)
    (B / 'edl.js').write_text('window.EDL=' + json.dumps({'shots': edl, 'total': total}), encoding='utf-8')
    music(total)
    if '--no-render' not in sys.argv:
        render(total)
