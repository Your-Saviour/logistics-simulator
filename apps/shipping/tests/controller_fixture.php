<?php
declare(strict_types=1);
require __DIR__.'/../vendor/autoload.php';
$settings=new Shipping\Settings();$db=new Shipping\Database($settings);$db->migrate();Shipping\Controller::run(new Shipping\Ledger($db,$settings),$settings);
