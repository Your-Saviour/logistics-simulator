<?php
declare(strict_types=1);
require __DIR__.'/../vendor/autoload.php';
use Shipping\{Settings,Validation};
function check(bool $ok,string $name):void{if(!$ok)throw new RuntimeException($name);echo "PASS $name\n";}
$settings=new Settings();
$operator=$settings->identify('operator','shipping-smoke');check($operator!==null&&in_array('runs:control',$operator['scopes'],true),'operator control scope');
$employee=$settings->identify('employee','employee-smoke');check($employee!==null&&!in_array('runs:control',$employee['scopes'],true),'employee cannot control runs');
$service=$settings->identify('observer','observer-smoke');check($service!==null&&$service['scopes']===['status:read'],'service scopes explicitly narrowed');
check($settings->identify('operator','wrong')===null,'wrong password rejected');
check(!str_contains(json_encode($operator),'shipping-smoke'),'public identity never contains credentials');
$record=$settings->sessionRecord($operator);check($settings->sessionPrincipal($record)===$operator,'server session resolves configured identity');
$record['username']='employee';check($settings->sessionPrincipal($record)===null,'identity tampering fails credential version binding');
putenv('APP_IDENTITIES=[{"username":"evil","password":"secret","role":"service","scopes":["runs:control"]}]');
try{new Settings();throw new RuntimeException('service privilege escalation accepted');}catch(Validation){echo "PASS service cannot claim operator scope\n";}
