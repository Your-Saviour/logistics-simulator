import assert from 'node:assert/strict';
import { chromium } from '/opt/browser/node_modules/playwright/index.mjs';
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto('http://web/');await page.getByRole('heading',{name:'Log in'}).waitFor();await page.screenshot({path:'/artifacts/logistics-login.png',fullPage:true});
 await page.getByLabel('Username',{exact:true}).fill('operator');await page.getByLabel('Password',{exact:true}).fill('logistics-test-password');await page.getByRole('button',{name:'Log in',exact:true}).click();await page.getByRole('heading',{name:'Operator controls'}).waitFor();await page.getByRole('heading',{name:'Command audit'}).waitFor();await page.getByText('Platform diagnostics',{exact:true}).click();await page.getByRole('heading',{name:'Jobs',exact:true}).waitFor();await page.screenshot({path:'/artifacts/logistics-operator.png',fullPage:true});
 await page.getByRole('button',{name:'Log out'}).click();await page.getByLabel('Username',{exact:true}).fill('employee');await page.getByLabel('Password',{exact:true}).fill('employee-test-password');await page.getByRole('button',{name:'Log in',exact:true}).click();await page.getByRole('heading',{name:'Fleet availability'}).waitFor();assert.equal(await page.getByRole('heading',{name:'Operator controls'}).count(),0);assert.equal(await page.getByRole('heading',{name:'Command audit'}).count(),0);assert.deepEqual(errors,[]);console.log('browser login, operator jobs/audit/controls, employee scope visibility, and console checks passed');
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/artifacts/logistics-mobile.png',fullPage:true});
}finally{await browser.close()}
