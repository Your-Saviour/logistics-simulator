<?php
use Illuminate\Support\Facades\Artisan;
use Shipping\{Database,Ledger,Settings,Worker,Controller};
Artisan::command('simulator:migrate',function(Database $database){$database->migrate();});
Artisan::command('simulator:worker',function(Ledger $ledger,Settings $settings){Worker::run($ledger,$settings);});
Artisan::command('simulator:controller',function(Ledger $ledger,Settings $settings){Controller::run($ledger,$settings);});
