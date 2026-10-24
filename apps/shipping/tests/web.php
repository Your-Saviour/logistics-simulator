<?php
declare(strict_types=1);
require __DIR__.'/feature.php';
$response=httpRequest('/');$html=$response->getContent();if($response->getStatusCode()!==200||!str_contains($html,'Username')||!str_contains($html,'Password')||!str_contains($html,'Sign in'))throw new RuntimeException('Shipping sign-in form is not available');echo "PASS Blade sign-in form uses explicit identity fields\n";
