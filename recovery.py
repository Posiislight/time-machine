"""Checkpoint comparison and an explicitly deterministic, offline recovery demo."""
import csv
import difflib
import io
import json
from decimal import Decimal, ROUND_HALF_UP


def compare(store, run, checkpoint):
    if checkpoint not in {c['id'] for r in store.list_runs() for c in store.checkpoints(r['id'])}:
        raise ValueError('Checkpoint not found')
    source=store.root/'checkpoints'/checkpoint
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    before=set(manifest['hashes']); after={f['name'] for f in store.files(run)}
    changes=[]
    for name in sorted(before | after):
        old=(source/'files'/name).read_text(encoding='utf-8',errors='replace') if name in before else ''
        new=store.read(run,name) if name in after else ''
        status='added' if name not in before else 'removed' if name not in after else 'unchanged' if old==new else 'changed'
        changes.append({'path':name,'status':status,'diff':''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='checkpoint/'+name,tofile='workspace/'+name))})
    return changes


def repair_catalogue(store, run):
    output=io.StringIO(newline='')
    writer=csv.writer(output); writer.writerow(['product','selling_price'])
    for row in csv.DictReader(io.StringIO(store.read(run,'supplier.csv'))):
        pack=Decimal(row['pack_size']); price=Decimal(row['carton_price'])
        if not pack.is_finite() or not price.is_finite() or pack<=0 or price<0:
            raise ValueError('Pack sizes must be positive and prices nonnegative')
        amount=(price/pack*Decimal('1.30')).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
        writer.writerow([row['product'],str(amount)])
    store.checkpoint(run,'Before offline recovery')
    store.write(run,'catalogue.csv',output.getvalue())
    store.save_messages(run,store.messages(run)+[{'role':'assistant','content':'Offline demo (no AI call): divided carton prices by pack size, applied a 30% markup, and rounded to two decimal places.'}])
    store.checkpoint(run,'Corrected unit pricing - offline demo')
    store.status(run,'completed')
