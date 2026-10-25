import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
for(const app of ['manufacturing','logistics','twin']) test(`${app} checks isolate dependencies and remove their disposable volumes`,()=>{
 const dir=mkdtempSync(join(tmpdir(),'disposable-check-')),bin=join(dir,'bin'),log=join(dir,'calls');mkdirSync(bin);
 const stub='#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n';
 for(const command of ['python3','docker'])writeFileSync(join(bin,command),stub,{mode:0o755});
 try{
  const result=spawnSync('sh',[resolve('scripts/check_stack_unit.sh'),app],{env:{...process.env,PATH:bin+':'+process.env.PATH,CALL_LOG:log},encoding:'utf8'});
  assert.equal(result.status,0,result.stderr);
  const calls=readFileSync(log,'utf8').trim().split('\n');
  const cleanup=calls.find(call=>call.includes(' down'));
  assert.ok(cleanup?.includes('down --volumes'),'Test dependencies must not retain anonymous or named volumes');
  const projects=calls.map(call=>call.match(/compose -p (\S+)/)?.[1]).filter(Boolean);
  assert.ok(projects.length>0,'Checks must select a dedicated project');
  assert.equal(new Set(projects).size,1,'Setup and teardown must share the project');
  assert.match(projects[0],new RegExp('^simu-'+app+'-unit-[0-9]+$'),'Existing development projects must not be targeted');
 }finally{rmSync(dir,{recursive:true,force:true});}
});
