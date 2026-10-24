<?php
declare(strict_types=1);
namespace Shipping;
use Illuminate\Http\Request;
final class CommandMiddleware
{
    public function __construct(private readonly Settings $settings,private readonly Ledger $ledger){}
    public function handle(Request $request,\Closure $next):\Symfony\Component\HttpFoundation\Response {
        $command=$request->isMethod('POST');$audit=['request_id'=>Rules::uuid4(),'actor'=>'anonymous','role'=>'anonymous','action'=>$request->method().' '.$request->getPathInfo(),'idempotency_key'=>$request->header('Idempotency-Key',''),'peer'=>$request->ip()??''];$response=null;
        try{if($command)$audit['run_id']=$this->ledger->scope();
            if(!$request->is('api/health/*')){$principal=$this->settings->basic($request->header('Authorization'));if(!$principal)$response=response()->json(['detail'=>'Invalid username or password'],401);else{$audit['actor']=$principal['username'];$audit['role']=$principal['role'];$scope=$request->is('api/control/*')?'runs:control':($request->is('api/audit')?'audit:read':($command?'jobs:write':'status:read'));
                    if(!in_array($scope,$principal['scopes'],true))$response=response()->json(['detail'=>'This identity cannot perform the requested action'],403);else $request->attributes->set('shipping.identity',$principal);
                }}
            $request->attributes->set('shipping.audit',$audit);$response??=$next($request);
        }catch(Validation $error){$response=response()->json(['detail'=>$error->getMessage()],422);}catch(Conflict $error){$response=response()->json(['detail'=>$error->getMessage()],409);}catch(\PDOException){$response=response()->json(['detail'=>'Database unavailable; retry with the same idempotency key'],503);}
        finally{if($command&&$response&&$response->getStatusCode()>=400&&isset($audit['run_id']))try{$this->ledger->rejected($audit,$response->getStatusCode());}catch(\Throwable){error_log('Rejected command audit unavailable request_id='.$audit['request_id']);}}
        $response->headers->set('X-Request-ID',$audit['request_id']);return $response;
    }
}
