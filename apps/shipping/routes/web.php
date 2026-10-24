<?php
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;
use Shipping\Settings;
Route::get('/',function(Request $request,Settings $settings){$identity=$settings->sessionPrincipal($request->session()->get('shipping.identity'));if($identity)abort_unless(in_array('status:read',$identity['scopes'],true),403);return view('page',['identity'=>$identity]);});
Route::post('/signin',function(Request $request,Settings $settings){$username=$request->input('username');$password=$request->input('password');$identity=is_string($username)&&is_string($password)?$settings->identify($username,$password):null;if(!$identity)return redirect('/')->withErrors(['credentials'=>'Invalid username or password']);$request->session()->regenerate();$request->session()->put('shipping.identity',$settings->sessionRecord($identity));return redirect('/');});
Route::post('/signout',function(Request $request){$request->session()->invalidate();$request->session()->regenerateToken();return redirect('/');});
