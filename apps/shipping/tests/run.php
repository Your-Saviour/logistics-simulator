<?php
declare(strict_types=1);
// Mutation targets: accepting coercible quantities/unknown fields; naive DST
// arithmetic; non-deterministic input identity/quantity; role privilege leakage.
spl_autoload_register(function(string $class):void { if(str_starts_with($class,'Shipping\\')) { $file=__DIR__.'/../src/'.substr($class,9).'.php'; if(is_file($file)) require_once $file; } });
use Shipping\Rules;
use Shipping\Scenario;
use Shipping\Validation;
$count=0;
function check(bool $condition,string $name):void { global $count; if(!$condition) throw new RuntimeException($name); $count++; echo "PASS $name\n"; }
function invalid(callable $command,string $name):void { try { $command(); } catch(Validation) { check(true,$name);return; } throw new RuntimeException('Accepted invalid input: '.$name); }
$valid=Rules::job(Rules::object('{"due_at":1.5,"quantity":3}'));
check($valid===['due_at'=>1.5,'quantity'=>3],'valid fractional simulation seconds and strict item quantity');
foreach(['true','"1"','1.5','1.0','0','10001','null'] as $value) invalid(fn()=>Rules::job(Rules::object('{"due_at":1,"quantity":'.$value.'}')),'reject quantity '.$value);
foreach(['{"due_at":1,"quantity":1,"extra":true}','{"due_at":-1,"quantity":1}','{"quantity":1}','{"due_at":1}','[]','null'] as $raw) invalid(fn()=>Rules::job(Rules::object($raw)),'reject malformed command '.$raw);
invalid(fn()=>Rules::number(INF),'reject infinite time');invalid(fn()=>Rules::number(NAN),'reject NaN time');
$scenario=new Scenario([]);
check($scenario->instant(0)->format('Y-m-d\TH:i:sP')==='2026-01-05T08:00:00+10:30','scenario offset');
check($scenario->nextDue(9*3600-1,1)===86400.0,'closing rolls to next business opening');
$dst=new Scenario(['time_zone'=>'Australia/Adelaide','start_at'=>'2026-10-03T08:00:00+09:30','business_weekdays'=>[0,1,2,3,4,5,6]]);
check($dst->nextDue(9*3600,1)===23*3600.0,'business calendar respects elapsed UTC seconds across DST');
invalid(fn()=>new Scenario(['start_at'=>'2026-01-05T08:00:00']),'reject naive start time');
invalid(fn()=>new Scenario(['business_weekdays'=>[true]]),'reject boolean weekday');
invalid(fn()=>new Scenario(['business_open'=>'08:00:01']),'reject subminute opening');
invalid(fn()=>new Scenario(['time_zone'=>'No/SuchZone']),'reject unknown timezone');
check(Rules::quantity(1,'storage','supply',1)===2,'SHA256 seeded quantity preserves existing algorithm');
check(Rules::uuid5('6ba7b810-9dad-11d1-80b4-00c04fd430c8','www.widgets.com')==='21f7f8de-8051-5b89-8680-0195ef798b6a','RFC UUID5 identity compatibility');
check(Rules::uuid(Rules::uuid4())!==null,'generated event identity is UUID');
echo "$count domain checks passed\n";
