"""Prove that county verification preserved live observations and publications."""
import argparse
import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine
from app.models.state_results import StateResultBatch
from app.services.data005_snapshot import snapshot
from app.services.data005_reconcile import write
from app.services.fec_state_results import read_state_totals


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--before',type=Path,required=True)
    p.add_argument('--fec-baseline',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args()
    if args.output_dir.exists():
        raise ValueError('Refusing to replace live verification evidence')
    before=json.loads(args.before.read_text(encoding='utf-8'))
    fec_before=json.loads(args.fec_baseline.read_text(encoding='utf-8'))
    with Session(engine) as session,session.begin():
        session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        after=snapshot(session)
        states=read_state_totals(session,year=2008)
        batch=session.get(StateResultBatch,states['batch_id'])
        states['fingerprint']=batch.fingerprint
    if before['fingerprints']!=after['fingerprints']:
        raise ValueError('Live public table set/rows changed during county verification')
    if states['batch_id']!=fec_before['batch_id'] or states['fingerprint']!=fec_before['fingerprint']:
        raise ValueError('FEC authority batch/pointer changed')
    if len(states['results'])!=153 or sum(r['votes'] for r in states['results'])!=131313820:
        raise ValueError('FEC state results changed')
    args.output_dir.mkdir(parents=True,exist_ok=False)
    write(args.output_dir/'snapshot-after.json',after)
    write(args.output_dir/'state-authority.json',states)
    write(args.output_dir/'preservation.json',dict(transaction_read_only=after['read_only'],
        all_public_tables_unchanged=True,table_count=len(after['fingerprints']),
        same_table_set=True,county_batches_and_pointers_unchanged=True,
        source_observations_and_decisions_unchanged=True,
        fec_batch_and_pointer_unchanged=True,canonical_preview=after['preview'],
        stored_county_batch=after['stored_batch'],fec_batch_id=states['batch_id'],
        fec_fingerprint=states['fingerprint'],fec_state_votes=131313820,
        publication_attempted=False,alembic_revision=after['alembic_revision']))
    print(json.dumps(dict(tables_preserved=len(after['fingerprints']),fec_states=51,
        fec_votes=131313820,stored_county_votes=after['stored_batch']['canonical_votes'],
        current_county_preview=after['preview']),indent=2))


if __name__=='__main__':
    main()
