<?php
declare(strict_types=1);
namespace Shipping;
final class ShippingRules
{
    public static function code(mixed $value):string {
        $value=Rules::text($value,32);
        if(!preg_match('/^[A-Z0-9][A-Z0-9_-]{0,31}$/D',$value))throw new Validation('Code requires 1..32 uppercase letters, digits, underscore or hyphen');
        return $value;
    }
    public static function command(array $body):array {
        $body['run_id']=Rules::uuid($body['run_id']??null);$body['epoch']=Rules::uuid($body['epoch']??null);
        $body['due_at']=Rules::number($body['due_at']??null);if($body['due_at']<0)throw new Validation('Nonnegative due_at required');
        $action=$body['action']??null;
        if($action==='create'){
            Rules::fields($body,['run_id','epoch','due_at','action','customer','destination','lines']);
            $body['customer']=Rules::text($body['customer']??null,128);$body['destination']=self::code($body['destination']??null);
            $lines=$body['lines']??null;if(!is_array($lines)||!array_is_list($lines)||count($lines)<1||count($lines)>100)throw new Validation('Order requires 1..100 lines');
            $seen=[];foreach($lines as &$line){if(!is_array($line))throw new Validation('Line object required');Rules::fields($line,['sku','quantity']);$line['sku']=self::code($line['sku']??null);$line['quantity']=Rules::integer($line['quantity']??null,1,10000);if(isset($seen[$line['sku']]))throw new Validation('Duplicate SKU');$seen[$line['sku']]=true;}$body['lines']=$lines;
        }elseif($action==='intake'){
            Rules::fields($body,['run_id','epoch','due_at','action','sku','quantity','units']);$body['sku']=self::code($body['sku']??null);$body['quantity']=Rules::integer($body['quantity']??null,1,10000);if(!is_array($body['units']??null))throw new Validation('Whole-unit manifest required');$body['units']=HandlingUnits::manifest($body['units'],$body['quantity']);
        }elseif(in_array($action,['fulfil','pack','dispatch','cancel'],true)){
            Rules::fields($body,['run_id','epoch','due_at','action','reference']);$body['reference']=Rules::uuid($body['reference']??null);
        }else throw new Validation('Unknown shipping action');
        return $body;
    }
    public static function fact(array $body):array {
        Rules::fields($body,['intent_id','owner','result','reference','sku','quantity','destination','peer_reference','reason','units']);
        if(isset($body['units'])){if(!is_array($body['units']))throw new Validation('Whole-unit manifest required');$body['units']=HandlingUnits::manifest($body['units'],Rules::integer($body['quantity']??null,1,10000));}
        if(isset($body['reason']))Rules::text($body['reason'],1000);
        if(isset($body['peer_reference']))$body['peer_reference']=Rules::uuid($body['peer_reference']);
        $body['intent_id']=Rules::uuid($body['intent_id']??null);$body['reference']=Rules::uuid($body['reference']??null);
        $body['owner']=Rules::text($body['owner']??null,64);$body['result']=Rules::text($body['result']??null,32);
        if(!in_array($body['result'],['reserved','shortage','produced','picked','transferred','received','released','departed','delivered','failed'],true))throw new Validation('Unknown provider outcome');
        if(isset($body['sku']))self::code($body['sku']);if(isset($body['quantity']))Rules::integer($body['quantity'],1,10000);if(isset($body['destination']))self::code($body['destination']);
        return $body;
    }
}
