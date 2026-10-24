<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="csrf-token" content="{{ csrf_token() }}"><title>Shipping simulator</title><link rel="stylesheet" href="/style.css">@livewireStyles</head><body><main>
<header><div><p class="app-label">Logistics simulator</p><h1>Shipping<span>.</span></h1></div>@if($identity)<div class="identity"><span>{{ $identity['username'] }} / {{ $identity['role'] }}</span><form method="post" action="/signout">@csrf<button>Sign out</button></form></div>@else<span class="app-label">Sample execution foundation</span>@endif</header>
@if(!$identity)
<section class="login"><div><h2>Sign in</h2><p>Use an identity configured for this shipping deployment.</p>@if($errors->any())<p role="alert" class="error">{{ $errors->first() }}</p>@endif<form method="post" action="/signin">@csrf<label>Username<input name="username" autocomplete="username" required></label><label>Password<input name="password" type="password" autocomplete="current-password" required></label><button class="primary">Sign in</button></form></div><aside><h2>Sample execution</h2><p>Schedule quantities in simulation seconds. The foundation records completed sample work and boundary inputs.</p><p>Clock controls require an operator identity.</p></aside></section>
@else
@livewire('shipping-dashboard')
@endif
</main>@livewireScripts</body></html>
