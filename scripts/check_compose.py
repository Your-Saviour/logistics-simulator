#!/usr/bin/env python3
"""Exercise Compose parsing and dependency graphs without exposing secrets."""
import json
from pathlib import Path
import subprocess

apps=['manufacturing','storage','logistics','shipping','twin']
for app in apps+['suite']:
    manifest=Path('deploy/generated')/(app+'.json')
    output=subprocess.check_output(['docker','compose','-f',str(manifest),'config','--format','json'],text=True)
    value=json.loads(output)
    for name,service in value['services'].items():
        if app!='suite':
            assert name.startswith(app+'-')
            assert all(x.startswith(app+'-') for x in service.get('depends_on',{}))
        if name.endswith('-api'):
            assert service['environment']['APP_PASSWORD']
            assert 'localhost' not in service['environment']['DATABASE_URL']
        if name.endswith('-projection'):
            sources=json.loads(service['environment']['TWIN_SOURCES'])
            assert len(sources)==(4 if app=='suite' else 0)
    print(app+': Compose parsed; application dependencies and source configuration valid')
