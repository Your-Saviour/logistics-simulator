<?php
declare(strict_types=1);
namespace Shipping;

/** Native transactional intents; only relay() performs HTTP after SQL commit. */
final class Fleet
{
    public static function enabled():bool {return Settings::env('FLEET_MODE','disabled')==='coordinated';}
    public static function configure():void {
        if(!in_array(Settings::env('FLEET_MODE','disabled'),['disabled','coordinated'],true))throw new Validation('Invalid FLEET_MODE');
        if(!self::enabled())return;
        Rules::number((float)Settings::env('FLEET_TIME_OFFSET','0'));if(!is_numeric(Settings::env('FLEET_TIME_OFFSET','0'))||(float)Settings::env('FLEET_TIME_OFFSET','0')<0)throw new Validation('Invalid FLEET_TIME_OFFSET');
        Rules::uuid(Settings::env('FLEET_RUN_ID'));Rules::uuid(Settings::env('FLEET_EPOCH'));
        if(!preg_match('~^https?://~',Settings::env('FLEET_URL'))||!Settings::env('FLEET_TOKEN'))throw new Validation('Coordinated fleet requires URL and token');
    }
    public static function offset():float {return (float)Settings::env('FLEET_TIME_OFFSET','0');}
    public static function metadata():array {return ['mode'=>Settings::env('FLEET_MODE','disabled'),'run_id'=>Settings::env('FLEET_RUN_ID'),'epoch'=>Settings::env('FLEET_EPOCH')];}
    public static function request(array $r,array $h,bool $departure):array {
        $generation=$h['unit']['custody_generation']+($departure?1:0);
        return ['version'=>1,'id'=>Rules::uuid5($h['unit']['id'],'fleet:'.$h['id'].':'.$generation),'run_id'=>Settings::env('FLEET_RUN_ID'),'epoch'=>Settings::env('FLEET_EPOCH'),'producer'=>$h['source'],'source_run_id'=>$h['run_id'],'source_epoch'=>$h['epoch'],'unit_id'=>$h['unit']['id'],'origin'=>$h['origin'],'destination'=>$h['destination'],'custody_generation'=>$generation,'effective_time'=>$r['granted']];
    }
    public static function fact(array $request,array $body,string $kind,float $grant):bool {
        if(($body['job_id']??null)!==$request['id']||($body['kind']??null)!==$kind||($body['route_version']??null)!==1||!is_string($body['robot_id']??null)||(!is_int($body['effective_time']??null)&&!is_float($body['effective_time']??null))||!is_finite((float)$body['effective_time'])||$body['effective_time']<0||$body['effective_time']>$grant)return false;
        foreach(['unit_id','run_id','epoch','source_run_id','source_epoch','origin','destination','custody_generation'] as $field)if(($body[$field]??null)!==($request[$field]??null))return false;
        return true;
    }
    public static function gate(Unit $u,array $r,array $request,string $kind,bool $watch=false):void {
        if(!self::enabled())return;
        $u->execute('INSERT INTO shipping_fleet_jobs(id,run_id,epoch,request,admitted) VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING',[$request['id'],$r['id'],$r['epoch'],$request,$watch]);
        $old=$u->one('SELECT * FROM shipping_fleet_jobs WHERE id=?',[$request['id']]);
        if($old['run_id']!==$r['id']||$old['epoch']!==$r['epoch'])throw new Conflict('Fleet native scope changed');
        foreach(['id','run_id','epoch','producer','unit_id','source_run_id','source_epoch','origin','destination','custody_generation'] as $field)if($old['request'][$field]!==$request[$field])throw new Conflict('Fleet immutable request changed: '.$field);
        foreach($old['snapshot']['events']??[] as $event)if(($event['job_id']??null)===$request['id']&&($event['kind']??null)===$kind&&is_array($event['body']??null)&&self::fact($old['request'],$event['body'],$kind,$r['granted']+self::offset()))return;
        throw new FleetWait('Waiting for coordinated fleet '.$kind);
    }
    public static function proof(Unit $u,array $r,array $request,string $kind):void {
        if(!self::enabled())return;
        if(!in_array($kind,['departure','receipt'],true))throw new Validation('Unsupported fleet proof');
        $body=['job_id'=>$request['id'],'unit_id'=>$request['unit_id'],'run_id'=>$request['run_id'],'epoch'=>$request['epoch'],'source_run_id'=>$r['id'],'source_epoch'=>$r['epoch'],'custody_generation'=>$request['custody_generation'],'endpoint'=>$request[$kind==='departure'?'origin':'destination'],'effective_time'=>$r['granted']];
        $u->execute('UPDATE shipping_fleet_jobs SET '.$kind.'=COALESCE('.$kind.',?::jsonb) WHERE id=? AND run_id=? AND epoch=?',[$body,$request['id'],$r['id'],$r['epoch']]);
    }
    private static function http(string $path,?array $body=null):array {
        $options=['method'=>$body===null?'GET':'POST','header'=>"Authorization: Bearer ".Settings::env('FLEET_TOKEN')."\r\nContent-Type: application/json\r\n",'timeout'=>2,'ignore_errors'=>true,'follow_location'=>0];
        if($body!==null)$options['content']=json_encode($body,JSON_THROW_ON_ERROR|JSON_PRESERVE_ZERO_FRACTION);
        $result=@file_get_contents(rtrim(Settings::env('FLEET_URL'),'/').$path,false,stream_context_create(['http'=>$options]));
        $headers=$http_response_header??[];if($result===false||!preg_match('~^HTTP/\S+ 2\d\d~',$headers[0]??''))throw new \RuntimeException('Fleet unavailable or rejected request');
        $value=json_decode($result,true,512,JSON_THROW_ON_ERROR);if(!is_array($value))throw new \RuntimeException('Malformed fleet response');return $value;
    }
    public static function relay(Database $db):void {
        if(!self::enabled())return;
        $jobs=$db->transaction(fn($u)=>$u->query("SELECT f.* FROM shipping_fleet_jobs f JOIN runs r ON r.id=f.run_id AND r.epoch=f.epoch AND r.current WHERE r.state IN ('running','held') AND NOT (COALESCE(f.snapshot->>'state'='completed',false) AND (f.departure IS NULL OR f.departure_sent) AND (f.receipt IS NULL OR f.receipt_sent)) ORDER BY f.updated_at,f.id LIMIT 16"));
        foreach($jobs as $job){$id=$job['id'];$path='/v1/jobs/'.$id;
            try{
                if(!$job['admitted']){self::http('/v1/jobs',$job['request']);$db->transaction(fn($u)=>$u->execute('UPDATE shipping_fleet_jobs SET admitted=true WHERE id=? AND run_id=? AND epoch=?',[$id,$job['run_id'],$job['epoch']]));}
                foreach(['departure','receipt'] as $kind)if($job[$kind]!==null&&!$job[$kind.'_sent']){self::http($path.'/proofs/'.$kind,$job[$kind]);$db->transaction(fn($u)=>$u->execute('UPDATE shipping_fleet_jobs SET '.$kind.'_sent=true WHERE id=? AND run_id=? AND epoch=?',[$id,$job['run_id'],$job['epoch']]));}
                $snapshot=self::http($path);$scope=$snapshot['fleet_scope']??[];if(($scope['run_id']??null)!==$job['run_id']||($scope['epoch']??null)!==$job['epoch']||($scope['offset']??null)!=self::offset())throw new \RuntimeException('Fleet scope mapping mismatch');foreach($job['request'] as $key=>$value)if($key!=='effective_time'&&($snapshot['request'][$key]??null)!=$value)throw new \RuntimeException('Fleet snapshot scope mismatch');
                $db->transaction(fn($u)=>$u->execute('UPDATE shipping_fleet_jobs SET snapshot=?,error=NULL,updated_at=clock_timestamp() WHERE id=? AND run_id=? AND epoch=?',[$snapshot,$id,$job['run_id'],$job['epoch']]));
            }catch(\Throwable $error){$db->transaction(fn($u)=>$u->execute('UPDATE shipping_fleet_jobs SET error=?,updated_at=clock_timestamp() WHERE id=?',[$error->getMessage(),$id]));return;}
        }
    }
}
