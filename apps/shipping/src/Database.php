<?php
declare(strict_types=1);
namespace Shipping;
final class Database
{
    public function __construct(private readonly Settings $settings){}
    public function connect():\PDO {
        $url=$this->settings->databaseUrl;$user=null;$password=null;
        if(str_starts_with($url,'postgres')){$parts=parse_url($url);if(!$parts||!isset($parts['host']))throw new Validation('Invalid PostgreSQL URL');$user=rawurldecode($parts['user']??'');$password=rawurldecode($parts['pass']??'');$options=['host'=>$parts['host'],'port'=>$parts['port']??5432,'dbname'=>rawurldecode(ltrim($parts['path']??'','/')),'connect_timeout'=>5];parse_str($parts['query']??'',$query);
            foreach($query as $key=>$value){if(!in_array($key,['sslmode','sslrootcert','sslcert','sslkey','sslpassword','connect_timeout','application_name','options','gssencmode'],true)||!is_string($value))throw new Validation('Unsupported PostgreSQL URL option');$options[$key]=$value;}
            $dsn='pgsql:';foreach($options as $key=>$value){if(str_contains((string)$value,';')||str_contains((string)$value,"\0"))throw new Validation('Unsupported PostgreSQL DSN separator');$dsn.=$key.'='.$value.';';}
        }elseif(str_starts_with($url,'pgsql:'))$dsn=$url;else throw new Validation('PostgreSQL URL or PDO pgsql DSN required');
        return new \PDO($dsn,$user,$password,[\PDO::ATTR_ERRMODE=>\PDO::ERRMODE_EXCEPTION,\PDO::ATTR_EMULATE_PREPARES=>false,\PDO::ATTR_STRINGIFY_FETCHES=>false]);
    }
    public function transaction(callable $action):mixed {$pdo=$this->connect();$pdo->beginTransaction();try{$u=new Unit($pdo);$u->execute('SELECT pg_advisory_xact_lock_shared(8192103)');$value=$action($u);$pdo->commit();return $value;}catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}}
    public function migrate():void {
        $pdo=$this->connect();$pdo->beginTransaction();try{$u=new Unit($pdo);$u->execute('SELECT pg_advisory_xact_lock(8192101)');$exists=$u->one("SELECT to_regclass('schema_migrations')::text AS name")['name'];$applied=[];if($exists)foreach($u->query('SELECT name,checksum FROM schema_migrations') as $row)$applied[$row['name']]=$row['checksum'];
            $files=glob(__DIR__.'/../migrations/*.sql');sort($files);$pending=[];foreach($files as $file){$name=basename($file);$sql=file_get_contents($file);$sum=hash('sha256',$sql);if(isset($applied[$name])){if(!hash_equals($applied[$name],$sum))throw new Conflict('Applied migration was edited: '.$name);}else $pending[]=[$name,$sql,$sum];}
            $u->execute($pending?'SELECT pg_advisory_xact_lock(8192103)':'SELECT pg_advisory_xact_lock_shared(8192103)');if($pending)$pdo->exec('CREATE TABLE IF NOT EXISTS schema_migrations(name text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz NOT NULL DEFAULT clock_timestamp())');
            foreach($pending as [$name,$sql,$sum]){$pdo->exec($sql);$u->execute('INSERT INTO schema_migrations(name,checksum) VALUES (?,?)',[$name,$sum]);}
            if(!$u->query('SELECT id FROM runs WHERE current'))$u->execute('INSERT INTO runs(id,epoch,mode,scenario) VALUES (?,?,?,?)',[$this->settings->mode==='helics'?$this->settings->runId:Rules::uuid4(),$this->settings->mode==='helics'?$this->settings->epoch:Rules::uuid4(),$this->settings->mode,$this->settings->scenario->body]);
            $r=$u->run();if(!$r['scenario'])$u->execute('UPDATE runs SET scenario=? WHERE id=?',[$this->settings->scenario->body,$r['id']]);
            if($r['mode']!==$this->settings->mode||$r['mode']==='helics'&&($r['id']!==$this->settings->runId||$r['epoch']!==$this->settings->epoch))throw new Conflict('Persisted run mode/federation identity differs; retain and archive database before cutover');$pdo->commit();
        }catch(\Throwable $e){if($pdo->inTransaction())$pdo->rollBack();throw $e;}
    }
}
