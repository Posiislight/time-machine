"""Shared helpers: find recordings and turn logged marks into times inside each recording."""
import json, subprocess
from pathlib import Path
import imageio_ffmpeg
import os
FILM = Path(os.environ.get('TM_FILM_DIR', Path(__file__).resolve().parents[1] / 'film'))
FF = imageio_ffmpeg.get_ffmpeg_exe()
MARKS = {}
for l in (FILM / 'marks.jsonl').read_text().splitlines():
    m = json.loads(l); MARKS[m['name']] = m['t']

def video(rec):
    return next((FILM / rec).glob('*.webm'))

def at(rec, mark, plus=0.0):
    """Seconds into recording `rec` where `mark` was logged."""
    return MARKS[mark] - json.loads((FILM / (rec + '.json')).read_text())['t0'] + plus

def grab(rec, t, out):
    subprocess.run([FF, '-y', '-i', str(video(rec)), '-ss', '%.2f' % t, '-frames:v', '1', str(out)], check=True, capture_output=True)
