"""Command audit metadata intentionally excludes request bodies and credentials."""
from uuid import uuid4


def write_audit(db, run_id, context, outcome, status_code, target_id=None):
    if context is None:
        return
    db.execute('INSERT INTO command_audit(id,run_id,actor,role,request_id,action,outcome,status_code,idempotency_key,peer,target_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
               (uuid4(),run_id,context['actor'],context['role'],context['request_id'],context['action'][:256],outcome,status_code,context.get('idempotency_key','')[:128],context.get('peer','')[:128],target_id))
