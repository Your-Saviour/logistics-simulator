<?php
use Illuminate\Foundation\Application;
use Illuminate\Foundation\Configuration\{Middleware,Exceptions};
use Shipping\{CommandMiddleware,Validation,Conflict};
$app=Application::configure(basePath:dirname(__DIR__))
    ->withRouting(web:__DIR__.'/../routes/web.php',api:__DIR__.'/../routes/api.php',commands:__DIR__.'/../routes/console.php')
    ->withMiddleware(function(Middleware $middleware):void{$middleware->appendToGroup('api',CommandMiddleware::class);})
    ->withExceptions(function(Exceptions $exceptions):void{
        $exceptions->render(fn(Validation $e,Illuminate\Http\Request $r)=>$r->is('api/*')?response()->json(['detail'=>$e->getMessage()],422):null);
        $exceptions->render(fn(Conflict $e,Illuminate\Http\Request $r)=>$r->is('api/*')?response()->json(['detail'=>$e->getMessage()],409):null);
        $exceptions->render(fn(PDOException $e,Illuminate\Http\Request $r)=>$r->is('api/*')?response()->json(['detail'=>'Database unavailable; retry with the same idempotency key'],503):null);
        $exceptions->dontReport([Validation::class,Conflict::class]);
    })->create();
$app->useAppPath(dirname(__DIR__).'/src');
return $app;
