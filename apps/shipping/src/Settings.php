<?php
declare(strict_types=1);
namespace Shipping;
final class Settings
{
    public string $role,$mode,$databaseUrl,$amqpUrl,$federationId,$runId,$epoch,$adapterUrl,$adapterToken;
    public float $quantum,$timeout;
    public array $providers,$peers,$outputs;
    public Scenario $scenario;
    private array $accounts=[];
    private string $appKey;
    private const PERMISSIONS=['operator'=>['audit:read','jobs:write','runs:control','status:read'],'employee'=>['jobs:write','status:read'],'service'=>['jobs:write','status:read']];
    public static function env(string $key,string $default=''):string {$value=getenv($key);return $value===false?$default:$value;}
    private static function json(string $key,string $default):array {try{$value=json_decode(self::env($key,$default),true,512,JSON_THROW_ON_ERROR);}catch(\JsonException){throw new Validation("Invalid JSON configuration: $key");}if(!is_array($value))throw new Validation("JSON object/array required: $key");return $value;}
    public function __construct(){
        Fleet::configure();
        $this->role=self::env('ROLE','api');$this->mode=self::env('CLOCK_MODE','standalone');if(self::env('SIMULATOR','shipping')!=='shipping'||!in_array($this->role,['api','worker','controller'],true)||!in_array($this->mode,['standalone','helics'],true))throw new Validation('Invalid application, role or clock mode');
        $quantum=self::env('HANDOFF_QUANTUM','1');if(!is_numeric($quantum)||!is_finite((float)$quantum)||(float)$quantum<1)throw new Validation('Finite handoff quantum of at least one second required');$this->quantum=(float)$quantum;
        $timeout=self::env('HELICS_TIMEOUT_SECONDS','60');if(!is_numeric($timeout)||!is_finite((float)$timeout)||(float)$timeout<=0)throw new Validation('Positive adapter timeout required');$this->timeout=(float)$timeout;
        $this->databaseUrl=Rules::text(self::env('DATABASE_URL'));$this->amqpUrl=Rules::text(self::env('AMQP_URL'));
        $this->providers=self::json('BOUNDARY_PROVIDERS','{}');if(!$this->providers&&$this->mode==='standalone')$this->providers=['orders'=>'synthetic','goods'=>'synthetic','carrier'=>'synthetic'];
        if(count($this->providers)!==3||array_diff(['orders','goods','carrier'],array_keys($this->providers)))throw new Validation('Exactly one provider for orders, goods and carrier required');
        foreach($this->providers as $value)if(!in_array($value,['synthetic','helics'],true)||$this->mode==='standalone'&&$value!=='synthetic')throw new Validation('Invalid boundary provider for clock mode');
        $this->federationId=self::env('FEDERATION_ID');$this->runId=self::env('FEDERATION_RUN_ID');$this->epoch=self::env('FEDERATION_EPOCH');$this->adapterUrl=self::env('HELICS_ADAPTER_URL');$this->adapterToken=self::env('HELICS_ADAPTER_TOKEN');
        if($this->mode==='helics'){Rules::uuid($this->runId);Rules::uuid($this->epoch);if(!in_array('helics',$this->providers,true)||!$this->federationId||!$this->adapterUrl||!$this->adapterToken)throw new Validation('Connected mode requires explicit federation identity, providers and private adapter credentials');}
        $this->peers=self::json('HELICS_PEERS','{}');$this->outputs=self::json('HELICS_OUTPUTS','[]');$this->scenario=new Scenario(self::json('SCENARIO','{}'));
        $key=self::env('APP_KEY');$decoded=str_starts_with($key,'base64:')?base64_decode(substr($key,7),true):$key;if(!is_string($decoded)||strlen($decoded)!==32)throw new Validation('APP_KEY must contain an independently generated 32-byte Laravel encryption key');$this->appKey=$decoded;
        $accounts=self::json('APP_IDENTITIES','[]');if(!array_is_list($accounts))throw new Validation('APP_IDENTITIES must be a list');array_unshift($accounts,['username'=>self::env('APP_USERNAME','operator'),'password'=>self::env('APP_PASSWORD'),'role'=>'operator']);
        foreach($accounts as $account){if(!is_array($account))throw new Validation('Identity object required');$username=Rules::text($account['username']??null);$password=Rules::text($account['password']??null);$role=Rules::text($account['role']??null);if(str_contains($username,':')||isset($this->accounts[$username])||!isset(self::PERMISSIONS[$role]))throw new Validation('Invalid or duplicate identity');
            $scopes=$account['scopes']??($role==='service'?[]:self::PERMISSIONS[$role]);if(!is_array($scopes)||!array_is_list($scopes)||array_filter($scopes,fn($x)=>!is_string($x))||array_diff($scopes,self::PERMISSIONS[$role]))throw new Validation('Identity permissions exceed role');$scopes=array_values(array_unique($scopes));sort($scopes);$this->accounts[$username]=['username'=>$username,'password'=>$password,'role'=>$role,'scopes'=>$scopes];
        }
    }
    private function publicIdentity(array $account):array {return array_intersect_key($account,array_flip(['username','role','scopes']));}
    public function identify(string $username,string $password):?array {$found=null;foreach($this->accounts as $account){$user=hash_equals(hash('sha256',$account['username']),hash('sha256',$username));$pass=hash_equals(hash('sha256',$account['password']),hash('sha256',$password));if($user&$pass)$found=$this->publicIdentity($account);}return $found;}
    public function basic(?string $header):?array {if(!is_string($header)||!str_starts_with(strtolower($header),'basic '))return null;$raw=base64_decode(substr($header,6),true);if(!is_string($raw)||!str_contains($raw,':'))return null;[$user,$pass]=explode(':',$raw,2);return $this->identify($user,$pass);}
    public function sessionRecord(array $principal):array {$account=$this->accounts[$principal['username']]??throw new Validation('Unknown identity');return ['username'=>$account['username'],'credential_version'=>hash_hmac('sha256',$account['username']."\0".$account['password']."\0".json_encode([$account['role'],$account['scopes']],JSON_THROW_ON_ERROR),$this->appKey)];}
    public function sessionPrincipal(mixed $record):?array {if(!is_array($record)||!is_string($record['username']??null)||!is_string($record['credential_version']??null))return null;$account=$this->accounts[$record['username']]??null;if(!$account)return null;$expected=$this->sessionRecord($account);return hash_equals($expected['credential_version'],$record['credential_version'])?$this->publicIdentity($account):null;}
}
