<?php
declare(strict_types=1);
namespace Shipping;
final class CustodyQuarantine
{
    public static function seen(Unit $u,array $r,array $e):bool {return (bool)$u->query('SELECT 1 FROM shipping_custody_quarantine WHERE run_id=? AND epoch=? AND event_id=? AND envelope=?::jsonb',[$r['id'],$r['epoch'],$e['event_id'],$e]);}
    public static function record(Unit $u,array $r,array $e,string $endpoint,string $phase,string $reason,?string $command=null):void {
        if($u->query('SELECT 1 FROM shipping_custody_quarantine WHERE run_id=? AND epoch=? AND event_id=? AND envelope=?::jsonb AND phase=? AND reason=?',[$r['id'],$r['epoch'],$e['event_id'],$e,$phase,$reason]))return;
        $u->execute('INSERT INTO shipping_custody_quarantine(id,run_id,epoch,event_id,envelope,endpoint,phase,reason,command_id,simulation_time) VALUES (?,?,?,?,?,?,?,?,?,?)',[Rules::uuid4(),$r['id'],$r['epoch'],$e['event_id'],$e,$endpoint,$phase,$reason,$command,$r['granted']]);
    }
    public static function snapshot(Unit $u,array $r):array {return $u->query('SELECT * FROM shipping_custody_quarantine WHERE run_id=? AND epoch=? ORDER BY recorded_at,id',[$r['id'],$r['epoch']]);}
}
