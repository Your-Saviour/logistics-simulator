"""Compact physical samples; archive each immutable reservation set once."""
import hashlib
import json


def sample_frame(value):
    claims=sorted((item['resource'],item['job_id']) for item in value['reservations'])
    digest=hashlib.sha256(json.dumps(claims,separators=(',',':')).encode()).hexdigest()
    run=value['run']
    return {'revision':run['revision'],'committed':run['committed'],'state':run['state'],
            'robots':value['robots'],'reservation_count':len(claims),
            'reservation_digest':digest},claims
