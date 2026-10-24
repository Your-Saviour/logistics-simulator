<?php
declare(strict_types=1);
namespace Shipping;
final class Rules
{
    public static function object(string $raw):array {
        try{$value=json_decode($raw,false,512,JSON_THROW_ON_ERROR);if(!$value instanceof \stdClass)throw new Validation('JSON object required');return json_decode($raw,true,512,JSON_THROW_ON_ERROR);}catch(\JsonException){throw new Validation('Valid JSON object required');}
    }
    public static function fields(array $body,array $allowed):void {if(array_diff(array_keys($body),$allowed))throw new Validation('Unknown field');}
    public static function number(mixed $value):float {if((!is_int($value)&&!is_float($value))||!is_finite((float)$value))throw new Validation('Finite numeric value required');return (float)$value;}
    public static function integer(mixed $value,int $min,int $max):int {if(!is_int($value)||$value<$min||$value>$max)throw new Validation("Integer between $min and $max required");return $value;}
    public static function text(mixed $value,int $max=PHP_INT_MAX):string {if(!is_string($value)||$value===''||strlen($value)>$max)throw new Validation('Nonempty string required');return $value;}
    public static function uuid(mixed $value):string {$value=self::text($value);if(!preg_match('/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/iD',$value))throw new Validation('UUID required');return strtolower($value);}
    public static function uuid4():string {$bytes=random_bytes(16);$bytes[6]=chr((ord($bytes[6])&15)|64);$bytes[8]=chr((ord($bytes[8])&63)|128);return self::formatUuid($bytes);}
    public static function uuid5(string $namespace,string $name):string {$hash=sha1(hex2bin(str_replace('-','',self::uuid($namespace))).$name,true);$hash[6]=chr((ord($hash[6])&15)|80);$hash[8]=chr((ord($hash[8])&63)|128);return self::formatUuid(substr($hash,0,16));}
    private static function formatUuid(string $bytes):string {$s=bin2hex($bytes);return substr($s,0,8).'-'.substr($s,8,4).'-'.substr($s,12,4).'-'.substr($s,16,4).'-'.substr($s,20,12);}
    public static function job(array $body):array {self::fields($body,['due_at','quantity']);$due=self::number($body['due_at']??null);if($due<0)throw new Validation('Nonnegative due_at required');return ['due_at'=>$due,'quantity'=>self::integer($body['quantity']??null,1,10000)];}
    public static function quantity(int $seed,string $app,string $boundary,int $slot):int {return 1+unpack('N',substr(hash('sha256',"$seed:$app:$boundary:$slot",true),0,4))[1]%10;}
    public static function envelope(array $body):array {
        self::fields($body,['schema_version','type','event_id','federation_id','run_id','epoch','correlation_id','causation_id','aggregate_id','aggregate_version','source','destination','boundary','effective_time','wall_time','quantity_unit','payload']);
        foreach(['event_id','run_id','epoch','correlation_id','causation_id','aggregate_id'] as $key)$body[$key]=self::uuid($body[$key]??null);
        foreach(['federation_id','source','destination','boundary'] as $key)self::text($body[$key]??null,$key==='federation_id'?128:PHP_INT_MAX);
        if(($body['schema_version']??null)!=='1.0'||($body['type']??null)!=='sample.completed.v1'||($body['quantity_unit']??null)!=='item'||self::number($body['effective_time']??null)<0)throw new Validation('Invalid envelope version, type, unit or time');
        self::integer($body['aggregate_version']??null,1,PHP_INT_MAX);if(!is_array($body['payload']??null))throw new Validation('Payload required');self::fields($body['payload'],['quantity']);self::integer($body['payload']['quantity']??null,1,10000);
        if(isset($body['wall_time'])){try{new \DateTimeImmutable(self::text($body['wall_time']));}catch(\Exception){throw new Validation('Invalid wall_time');}}
        return $body;
    }
}
