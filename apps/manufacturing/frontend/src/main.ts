import { bootstrapApplication } from '@angular/platform-browser';
import { Component, OnDestroy, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Api } from './api';
interface Job {id:string;due_at:number;original_due_at:number;payload:{quantity:number};status:string;attempts:number;boundary_input?:{boundary:string;kind:string};}
interface Status {application:string;identity:{username:string;role:string;scopes:string[]};providers:Record<string,string>;quantum:number;simulation_time:string;run:{id:string;epoch:string;state:string;mode:string;granted:number;requested:number;committed:number;speed:number;blocked_reason?:string;error?:string;scenario:{time_zone:string;seed:number}};jobs:Job[];effects:number;pending_boundary_outputs:number;heartbeats:{role:string;healthy:boolean;seen_at:string}[];}
@Component({selector:'app-root',standalone:true,imports:[CommonModule,FormsModule],template:`
 <header><a href="/" class="brand">Manufacturing<span>Sample simulator</span></a><div class="header-right">@if(status();as s){<span>{{s.identity.username}} / {{s.identity.role}}</span><button (click)="logout()">Log out</button>}@else{<span>Independent application</span>}</div></header>
 <main>
 @if(!status()){
  <section class="login"><div class="section-number">01</div><h1>Manufacturing<br>simulator</h1><p>Sign in to view the run and schedule sample jobs.</p><form (ngSubmit)="login()"><label>Username<input name="username" [(ngModel)]="username" autocomplete="username" required></label><label>Password<input type="password" name="password" [(ngModel)]="password" autocomplete="current-password" required></label><button class="primary" [disabled]="busy()">{{busy()?'Signing in…':'Sign in'}}</button></form></section>
 }@else{
  @if(status();as s){
   <div class="run-heading"><div><span class="section-number">01 / Run</span><h1>{{s.run.state}}</h1></div><div class="time"><strong>{{s.run.granted | number:'1.0-2'}}<small> s</small></strong><span>{{s.simulation_time}}</span><span>{{s.run.scenario.time_zone}} · {{s.run.mode}}</span></div></div>
   @if(s.run.error){<p class="alert">{{s.run.error}}</p>}@if(s.run.blocked_reason){<p class="alert">{{s.run.blocked_reason}}</p>}
   <div class="metrics"><div><span>Completed items</span><strong>{{s.effects}}</strong></div><div><span>Requested time</span><strong>{{s.run.requested | number:'1.0-2'}}<small> s</small></strong></div><div><span>Committed time</span><strong>{{s.run.committed | number:'1.0-2'}}<small> s</small></strong></div><div><span>Pending outputs</span><strong>{{s.pending_boundary_outputs}}</strong></div></div>
   <div class="status-row"><div><span>Run</span><code>{{s.run.id}}</code></div><div><span>Epoch</span><code>{{s.run.epoch}}</code></div><div><span>Seed</span><code>{{s.run.scenario.seed}}</code></div></div>
   <div class="providers">@for(provider of s.providers | keyvalue;track provider.key){<span>{{provider.key}}<strong>{{provider.value}}</strong></span>}@for(h of s.heartbeats;track h.role){<span [class.unhealthy]="!h.healthy">{{h.role}}<strong>{{h.healthy?'Healthy':'Unavailable'}}</strong></span>}</div>
   <div class="workspace"><section><div class="section-heading"><h2><span>02</span> Sample jobs</h2><button (click)="refresh()" [disabled]="busy()">Refresh</button></div>
    @if(can('jobs:write')){<form class="job-form" (ngSubmit)="schedule()"><label>Due time (seconds)<input type="number" name="due" [(ngModel)]="due" [min]="s.run.requested+s.quantum" step="any" required></label><label>Quantity (items)<input type="number" name="quantity" [(ngModel)]="quantity" min="1" max="10000" step="1" required></label><button class="primary" [disabled]="busy()">Schedule</button><label class="key">Idempotency key<input name="key" [(ngModel)]="jobKey" maxlength="128" required></label></form>}
    <div class="table-wrap"><table><thead><tr><th>Job</th><th>Due (s)</th><th>Items</th><th>Source</th><th>Status</th></tr></thead><tbody>@for(job of s.jobs;track job.id){<tr><td><code [title]="job.id">{{job.id.slice(0,8)}}</code></td><td>{{job.due_at | number:'1.0-2'}}</td><td>{{job.payload.quantity}}</td><td>{{job.boundary_input?.boundary || 'Command'}}</td><td>{{job.status}}@if(job.attempts){<small> / {{job.attempts}} attempts</small>}</td></tr>}@empty{<tr><td colspan="5" class="empty">No jobs in this run.</td></tr>}</tbody></table></div>
   </section>
   @if(can('runs:control')){<aside><h2><span>03</span> Run controls</h2><div class="controls"><button [disabled]="busy()" (click)="control(s.run.state==='held'?'resume':'hold')">{{s.run.state==='held'?'Resume':'Hold'}}</button><button [disabled]="busy()" (click)="control('finalize')">Finalize</button></div>@if(s.run.mode==='standalone'){<label>Speed<select name="speed" [(ngModel)]="speed" (change)="control('speed',{speed:+speed})"><option [value]="1">1×</option><option [value]="5">5×</option><option [value]="20">20×</option><option [value]="60">60×</option></select></label><form (ngSubmit)="reset()"><label>Current run ID to confirm reset<input name="confirmation" [(ngModel)]="confirmation" autocomplete="off"></label><button [disabled]="busy() || confirmation!==s.run.id">Reset run</button></form>}<p class="note">Controls apply to this application. Due work and output delivery must settle before time advances.</p></aside>}
   </div>
   @if(can('audit:read')){<section class="audits"><div class="section-heading"><h2><span>04</span> Command audit</h2><button (click)="loadAudit()">Refresh audit</button></div><div class="table-wrap"><table><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Outcome</th><th>HTTP</th></tr></thead><tbody>@for(a of audit();track a.id){<tr><td>{{a.recorded_at | date:'short'}}</td><td>{{a.actor}} <small>{{a.role}}</small></td><td>{{a.action}}</td><td>{{a.outcome}}</td><td>{{a.status_code}}</td></tr>}@empty{<tr><td colspan="5" class="empty">No audit entries loaded.</td></tr>}</tbody></table></div></section>}
  }
 }
 @if(error()){<p class="error" role="alert">{{error()}}</p>}@if(message()){<p class="message" role="status">{{message()}}</p>}
 </main><footer>Manufacturing · Sample business execution</footer>
`})
export class App implements OnDestroy {
 username='';password='';status=signal<Status|null>(null);error=signal('');message=signal('');busy=signal(false);audit=signal<any[]>([]);
 due=1;quantity=1;speed=1;confirmation='';jobKey=crypto.randomUUID();api:Api|null=null;
 timer=setInterval(()=>{if(this.api&&!this.busy())void this.refresh();},3000);
 ngOnDestroy(){clearInterval(this.timer);}
 can(scope:string){return this.status()?.identity.scopes.includes(scope)??false;}
 async act(operation:()=>Promise<void>){this.busy.set(true);this.error.set('');this.message.set('');try{await operation();}catch(e){this.error.set(e instanceof Error?e.message:'Request failed');}finally{this.busy.set(false);}}
 async login(){await this.act(async()=>{const api=new Api(this.username,this.password);const s=await api.request('/status') as Status;this.api=api;this.password='';this.status.set(s);this.due=Math.max(s.run.granted,s.run.requested)+s.quantum;this.speed=s.run.speed;if(this.can('audit:read'))await this.loadAudit();});}
 logout(){this.api=null;this.status.set(null);this.audit.set([]);this.password='';this.error.set('');this.message.set('');}
 async refresh(){if(!this.api)return;try{this.status.set(await this.api.request('/status'));this.error.set('');}catch(e){this.error.set(e instanceof Error?e.message:'Status unavailable');}}
 async schedule(){await this.act(async()=>{await this.api!.request('/jobs','POST',{due_at:+this.due,quantity:+this.quantity},this.jobKey);this.jobKey=crypto.randomUUID();this.message.set('Job scheduled.');await this.refresh();});}
 async control(action:string,body:unknown={}){await this.act(async()=>{await this.api!.request('/control/'+action,'POST',body);await this.refresh();if(this.can('audit:read'))await this.loadAudit();});}
 async reset(){await this.control('reset',{confirm_run_id:this.confirmation});this.confirmation='';}
 async loadAudit(){if(this.api)try{this.audit.set(await this.api.request('/audit'));}catch(e){this.error.set(e instanceof Error?e.message:'Audit unavailable');}}
}
bootstrapApplication(App).catch(console.error);
