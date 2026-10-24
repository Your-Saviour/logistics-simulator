<?php
declare(strict_types=1);
namespace Shipping;
use Illuminate\Support\ServiceProvider;
final class AppServiceProvider extends ServiceProvider
{
    public function register():void {$this->app->singleton(Settings::class,fn()=>new Settings());$this->app->singleton(Database::class,fn($app)=>new Database($app->make(Settings::class)));$this->app->singleton(Ledger::class,fn($app)=>new Ledger($app->make(Database::class),$app->make(Settings::class)));}
    public function boot():void {\Livewire\Livewire::component('shipping-dashboard',Dashboard::class);}
}
