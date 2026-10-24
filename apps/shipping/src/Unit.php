<?php
declare(strict_types=1);
namespace Shipping;
final class Unit
{
    public function __construct(public readonly \PDO $pdo){}
    public function query(string $sql,array $args=[]):array {
        $statement=$this->pdo->prepare($sql);foreach(array_values($args) as $i=>$value){if(is_array($value)||is_object($value))$value=json_encode($value,JSON_THROW_ON_ERROR|JSON_PRESERVE_ZERO_FRACTION);$statement->bindValue($i+1,$value,$value===null?\PDO::PARAM_NULL:(is_bool($value)?\PDO::PARAM_BOOL:(is_int($value)?\PDO::PARAM_INT:\PDO::PARAM_STR)));}$statement->execute();
        if($statement->columnCount()===0)return [];$types=[];for($i=0;$i<$statement->columnCount();$i++){$meta=$statement->getColumnMeta($i);$types[$meta['name']]=$meta['native_type']??'';}
        $rows=$statement->fetchAll(\PDO::FETCH_ASSOC);foreach($rows as &$row)foreach($row as $name=>&$value){if($value===null)continue;$type=$types[$name];if(in_array($type,['json','jsonb'],true))$value=json_decode($value,true,512,JSON_THROW_ON_ERROR);elseif($type==='bool')$value=$value===true||$value==='t'||$value==='1';elseif(in_array($type,['int2','int4','int8'],true))$value=(int)$value;elseif(in_array($type,['float4','float8'],true))$value=(float)$value;}return $rows;
    }
    public function one(string $sql,array $args=[]):array {return $this->query($sql,$args)[0]??throw new Conflict('Expected durable row is missing');}
    public function execute(string $sql,array $args=[]):void {$this->query($sql,$args);}
    public function run():array {$this->execute('SELECT pg_advisory_xact_lock_shared(8192103)');for($n=0;$n<10;$n++){$rows=$this->query('SELECT * FROM runs WHERE current FOR UPDATE');if($rows)return $rows[0];}throw new Conflict('Current run changed repeatedly; retry command');}
}
