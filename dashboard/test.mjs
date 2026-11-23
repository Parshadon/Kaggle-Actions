import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import worker,{validTunnel} from './worker.mjs';

function fixture(){
 const db=new DatabaseSync(':memory:');db.exec(readFileSync(new URL('./schema.sql',import.meta.url),'utf8'));
 return {ADMIN_PASSWORD:'test-owner-password-only',BRIDGE_TOKEN:'test-bridge-token-at-least-32-chars',GITHUB_TOKEN:'test-github-token',GITHUB_REPO:'example/peakcut',GITHUB_REF:'main',
 ASSETS:{fetch:async()=>new Response('<html>test</html>')},DB:{prepare(sql){let values=[];const statement={bind(...args){values=args;return statement},async first(){return db.prepare(sql).get(...values)},async all(){return {results:db.prepare(sql).all(...values)}},async run(){const out=db.prepare(sql).run(...values);return {meta:{changes:Number(out.changes)}}}};return statement},async batch(items){return Promise.all(items.map(i=>i.run()))}}};
}
const origin='https://studio.example.com';
test('explicit HTML asset routing disables canonical redirects',async()=>{
 const config=JSON.parse(readFileSync(new URL('./wrangler.jsonc',import.meta.url),'utf8'));
 assert.equal(config.assets.html_handling,'none');
 const env=fixture();env.ASSETS.fetch=async request=>{
   assert.equal(new URL(request.url).pathname,'/index.html');
   return new Response('<html>Dashboard</html>',{headers:{'Content-Type':'text/html'}});
 };
 const response=await worker.fetch(new Request(origin+'/control'),env);
 assert.equal(response.status,200);assert.equal(response.headers.has('Location'),false);
});
function request(path,{method='GET',data,cookie,token,from=origin}={}){const headers={};if(cookie)headers.Cookie=cookie;if(token)headers.Authorization='Bearer '+token;if(method!=='GET')headers.Origin=from;return new Request(origin+path,{method,headers,body:data?JSON.stringify(data):undefined});}
async function login(env){const r=await worker.fetch(request('/control/api/login',{method:'POST',data:{password:env.ADMIN_PASSWORD}}),env);assert.equal(r.status,200);return r.headers.get('set-cookie').split(';')[0];}

test('control endpoints require auth, login cookie is secure, and CSRF is rejected',async()=>{
 const env=fixture();assert.equal((await worker.fetch(request('/control/api/status'),env)).status,401);
 const cookie=await login(env);const status=await worker.fetch(request('/control/api/status',{cookie}),env);assert.equal(status.status,200);assert.equal((await status.json()).online,false);
 assert.equal((await worker.fetch(request('/control/api/start',{method:'POST',cookie,data:{},from:'https://evil.test'}),env)).status,403);
 assert.equal((await worker.fetch(request('/app'),env)).status,302);
});
test('bridge rejects unsafe origins, preserves history, and never reveals tunnel URL in status',async()=>{
 const env=fixture(),cookie=await login(env);
 assert.equal(validTunnel('https://abc.trycloudflare.com'),true);assert.equal(validTunnel('https://localhost/'),false);assert.equal(validTunnel('https://abc.trycloudflare.com.evil.test'),false);
 const heartbeat={run_id:'one',tunnel_url:'https://test.trycloudflare.com',online:true,jobs:[{id:'job1',title:'Example',status:'done',clips:[]}],accounts:[],posting:{posts:[]}};
 assert.equal((await worker.fetch(request('/bridge/heartbeat',{method:'POST',data:heartbeat,token:'wrong'}),env)).status,401);
 assert.equal((await worker.fetch(request('/bridge/heartbeat',{method:'POST',data:{...heartbeat,tunnel_url:'http://127.0.0.1'},token:env.BRIDGE_TOKEN}),env)).status,400);
 assert.equal((await worker.fetch(request('/bridge/heartbeat',{method:'POST',data:heartbeat,token:env.BRIDGE_TOKEN}),env)).status,200);
 const status=await (await worker.fetch(request('/control/api/status',{cookie}),env)).json();assert.equal(status.online,true);assert.equal(status.snapshot.jobs.length,1);assert.equal(JSON.stringify(status).includes('trycloudflare'),false);
 assert.equal((await worker.fetch(request('/bridge/heartbeat',{method:'POST',data:{...heartbeat,run_id:'two'},token:env.BRIDGE_TOKEN}),env)).status,409);
 await worker.fetch(request('/bridge/offline',{method:'POST',data:{run_id:'one'},token:env.BRIDGE_TOKEN}),env);
 await worker.fetch(request('/bridge/heartbeat',{method:'POST',data:{...heartbeat,run_id:'two',jobs:[]},token:env.BRIDGE_TOKEN}),env);
 const next=await (await worker.fetch(request('/control/api/status',{cookie}),env)).json();assert.equal(next.snapshot.jobs[0].previous_session,true);
});
test('session start is dispatched once; duplicate clicks do not submit another GPU run',async()=>{
 const env=fixture(),cookie=await login(env);const saved=globalThis.fetch;let calls=0;
 globalThis.fetch=async(url,options)=>{calls++;assert.match(String(url),/start-kaggle.yml\/dispatches$/);assert.equal(JSON.parse(options.body).ref,'main');return new Response(null,{status:204});};
 try{const r=await worker.fetch(request('/control/api/start',{method:'POST',data:{},cookie}),env);assert.equal(r.status,202);assert.equal((await worker.fetch(request('/control/api/start',{method:'POST',data:{},cookie}),env)).status,409);assert.equal(calls,1);}finally{globalThis.fetch=saved;}
});
test('proxy preserves upstream auth and range requests, strips dashboard cookie',async()=>{
 const env=fixture(),cookie=await login(env),saved=globalThis.fetch;
 await worker.fetch(request('/bridge/heartbeat',{method:'POST',token:env.BRIDGE_TOKEN,data:{run_id:'one',tunnel_url:'https://test.trycloudflare.com',jobs:[],accounts:[],online:true}}),env);
 globalThis.fetch=async(url,options)=>{assert.equal(String(url),'https://test.trycloudflare.com/media/job/clip.mp4');assert.equal(options.headers.get('Cookie').trim(),'peakcut_session=example');assert.equal(options.headers.get('Range'),'bytes=0-9');return new Response('0123456789',{status:206});};
 try{const req=request('/media/job/clip.mp4',{cookie:cookie+'; peakcut_session=example'});req.headers.set('Range','bytes=0-9');assert.equal((await worker.fetch(req,env)).status,206);}finally{globalThis.fetch=saved;}
});
test('Stop requires owner auth, targets only the active compatible run, and survives heartbeats',async()=>{
 const env=fixture(),cookie=await login(env);
 assert.equal((await worker.fetch(request('/control/api/stop',{method:'POST',data:{}}),env)).status,401);
 const data={run_id:'one',protocol:2,tunnel_url:'https://test.trycloudflare.com',jobs:[],accounts:[],online:true};
 await worker.fetch(request('/bridge/heartbeat',{method:'POST',token:env.BRIDGE_TOKEN,data}),env);
 assert.equal((await worker.fetch(request('/control/api/stop',{method:'POST',data:{},cookie}),env)).status,202);
 let response=await worker.fetch(request('/bridge/heartbeat',{method:'POST',token:env.BRIDGE_TOKEN,data}),env);
 assert.equal((await response.json()).stop_requested,true);
 await worker.fetch(request('/bridge/offline',{method:'POST',token:env.BRIDGE_TOKEN,data:{run_id:'one'}}),env);
 response=await worker.fetch(request('/bridge/heartbeat',{method:'POST',token:env.BRIDGE_TOKEN,data:{...data,run_id:'two'}}),env);
 assert.equal((await response.json()).stop_requested,false);
});
