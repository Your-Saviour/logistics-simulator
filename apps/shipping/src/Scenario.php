<?php
declare(strict_types=1);
namespace Shipping;
final class Scenario
{
    public readonly array $body;
    public readonly \DateTimeZone $zone;
    public readonly \DateTimeImmutable $start;
    public readonly int $seed,$interval;
    public readonly string $open,$close;
    public readonly array $weekdays;
    public function __construct(array $body){
        Rules::fields($body,['seed','time_zone','start_at','business_open','business_close','business_weekdays','interval_seconds']);
        $this->seed=Rules::integer($body['seed']??1,0,2147483647);$this->interval=Rules::integer($body['interval_seconds']??30,1,86400);
        $zone=Rules::text($body['time_zone']??'Australia/Adelaide');if(!in_array($zone,\DateTimeZone::listIdentifiers(\DateTimeZone::ALL_WITH_BC),true))throw new Validation('Unknown scenario timezone');$this->zone=new \DateTimeZone($zone);
        $start=Rules::text($body['start_at']??'2026-01-05T08:00:00+10:30');if(!preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})$/D',$start))throw new Validation('Scenario start_at needs an explicit UTC offset');
        try{$this->start=new \DateTimeImmutable($start);$errors=\DateTimeImmutable::getLastErrors();if($errors&&($errors['warning_count']||$errors['error_count']))throw new Validation('Invalid scenario start');}catch(\Exception){throw new Validation('Invalid scenario start');}
        $this->open=self::wall($body['business_open']??'08:00:00');$this->close=self::wall($body['business_close']??'17:00:00');if($this->open>=$this->close)throw new Validation('Business hours must increase within one day');
        $days=$body['business_weekdays']??[0,1,2,3,4];if(!is_array($days)||!array_is_list($days)||!$days||count(array_unique($days,SORT_REGULAR))!==count($days))throw new Validation('Unique business weekdays required');foreach($days as $day)Rules::integer($day,0,6);$this->weekdays=$days;
        $this->body=['seed'=>$this->seed,'time_zone'=>$zone,'start_at'=>$this->start->format('Y-m-d\TH:i:s.uP'),'business_open'=>$this->open,'business_close'=>$this->close,'business_weekdays'=>$days,'interval_seconds'=>$this->interval];
    }
    private static function wall(mixed $value):string {if(!is_string($value)||!preg_match('/^(\d{2}):(\d{2})(?::00(?:\.0{1,6})?)?$/D',$value,$m)||(int)$m[1]>23||(int)$m[2]>59)throw new Validation('Whole local minute required');return $m[1].':'.$m[2].':00';}
    public function instant(float $seconds):\DateTimeImmutable {$value=Rules::number($seconds)+(float)$this->start->format('U.u');$date=\DateTimeImmutable::createFromFormat('U.u',sprintf('%.6F',$value));if(!$date)throw new Validation('Scenario time outside supported calendar');return $date->setTimezone($this->zone);}
    public function nextDue(float $after,float $delay):float {
        if(!is_finite($after)||!is_finite($delay)||$after<0||$delay<=0)throw new Validation('Finite nonnegative time and positive delay required');
        $candidate=$this->instant($after+$delay);$clock=$candidate->format('H:i:s.u');if(in_array((int)$candidate->format('N')-1,$this->weekdays,true)&&$clock>=$this->open&&$clock<$this->close)return $after+$delay;
        for($dayOffset=0;$dayOffset<8;$dayOffset++){$day=$candidate->modify("+$dayOffset day");if(!in_array((int)$day->format('N')-1,$this->weekdays,true))continue;
            $wall=\DateTimeImmutable::createFromFormat('!Y-m-d H:i:s',$day->format('Y-m-d').' '.$this->open,new \DateTimeZone('UTC'));if(!$wall)continue;
            for($minute=0;$minute<=180;$minute++){$naive=$wall->getTimestamp()+$minute*60;$offsets=[];foreach($this->zone->getTransitions($naive-172800,$naive+172800)?:[] as $t)$offsets[$t['offset']]=true;$stamps=[];
                foreach(array_keys($offsets) as $offset){$stamp=$naive-$offset;$resolved=(new \DateTimeImmutable('@'.$stamp))->setTimezone($this->zone);if($resolved->format('Y-m-d H:i:s')===gmdate('Y-m-d H:i:s',$naive))$stamps[]=$stamp;}
                if(!$stamps)continue;sort($stamps);foreach($stamps as $stamp){$resolved=(new \DateTimeImmutable('@'.$stamp))->setTimezone($this->zone);if($stamp>=(float)$candidate->format('U.u')&&$resolved->format('H:i:s')<$this->close)return $stamp-(float)$this->start->format('U.u');}break;
            }
        }throw new Validation('No valid business opening within the next week');
    }
}
