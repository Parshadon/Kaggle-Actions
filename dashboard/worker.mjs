const encoder = new TextEncoder();
const json = (data, status=200, extra={}) => new Response(JSON.stringify(data), {status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...extra}});
export const validTunnel = value => /^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/.test(value || '');
const now = () => Math.floor(Date.now()/1000);
async function digest(value) {return new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(value || '')));}
async function equal(a,b) {const x=await digest(a),y=await digest(b);let d=0;for(let i=0;i<x.length;i++)d|=x[i]^y[i];return d===0;}
async function sign(value, secret) {const key=await crypto.subtle.importKey('raw',encoder.encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);return btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.sign('HMAC',key,encoder.encode(value)))));}
async function loggedIn(request,env) {
  const token=(request.headers.get('Cookie')||'').split(';').map(x=>x.trim()).find(x=>x.startsWith('pc_control='))?.slice(11);
  if(!token)return false; const [expiry,signature]=token.split('.');
  return Number(expiry)>now() && Number(expiry)<now()+86401 && await equal(signature,await sign(expiry,env.ADMIN_PASSWORD));
}
async function read(env,key) {const row=await env.DB.prepare('SELECT value,updated FROM state WHERE key=?').bind(key).first();return row?{...JSON.parse(row.value),updated:row.updated}:null;}
async function write(env,key,value) {await env.DB.prepare('INSERT INTO state(key,value,updated) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated=excluded.updated').bind(key,JSON.stringify(value),now()).run();}
const online = state => state?.online && state.updated > now()-90;
async function body(request,max=500000) {if(Number(request.headers.get('Content-Length'))>max)throw new Error('Request too large');const text=await request.text();if(text.length>max)throw new Error('Request too large');return JSON.parse(text);}

export default {async fetch(request,env) {
  const url=new URL(request.url),path=url.pathname;
  if(!env.ADMIN_PASSWORD || env.ADMIN_PASSWORD.length<12 || !env.BRIDGE_TOKEN || env.BRIDGE_TOKEN.length<32)
    return json({error:'Configure ADMIN_PASSWORD (12+ characters) and BRIDGE_TOKEN (32+ random characters) as Worker secrets.'},503);
  try {
    if(path.startsWith('/bridge/')) {
      if(!await equal(request.headers.get('Authorization'),'Bearer '+env.BRIDGE_TOKEN))return json({error:'Unauthorized'},401);
      if(request.method!=='POST')return json({error:'Method not allowed'},405);
      const data=await body(request); const previous=await read(env,'runtime');
      if(path==='/bridge/heartbeat') {
        if(!validTunnel(data.tunnel_url)||typeof data.run_id!=='string'||!Array.isArray(data.jobs))return json({error:'Invalid heartbeat'},400);
        if(online(previous)&&previous.run_id!==data.run_id)return json({error:'Another runtime is connected. Stop it first.'},409);
        await write(env,'runtime',{run_id:data.run_id,tunnel_url:data.tunnel_url,online:true,protocol:Number(data.protocol)||1});
        const prior=await read(env,'snapshot');
        const changed=data.jobs.slice(0,100).filter(job=>previous?.run_id!==data.run_id||JSON.stringify(prior?.jobs?.find(old=>old.id===job.id))!==JSON.stringify(job));
        await write(env,'snapshot',{jobs:data.jobs.slice(0,100),accounts:(data.accounts||[]).slice(0,30),posting:data.posting||{}});
        if(changed.length)await env.DB.batch(changed.map(job=>env.DB.prepare('INSERT INTO history(id,run_id,value,updated) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value,updated=excluded.updated').bind(data.run_id+':'+job.id,data.run_id,JSON.stringify(job),now())));
        await env.DB.prepare("UPDATE starts SET status='connected' WHERE status='requested'").run();
        const stop=await read(env,'stop');
        return json({ok:true,stop_requested:stop?.run_id===data.run_id});
      }
      if(path==='/bridge/offline') {
        if(previous?.run_id===data.run_id)await write(env,'runtime',{...previous,online:false});
        return json({ok:true});
      }
      return json({error:'Not found'},404);
    }
    if(path==='/control' || path==='/control/' || path==='/control/app.js' || path==='/control/style.css') {
      const asset=path.endsWith('.js')?'app.js':path.endsWith('.css')?'style.css':'index.html';
      const response=await env.ASSETS.fetch(new Request(new URL('/'+asset,url),request));
      const headers=new Headers(response.headers);headers.set('X-Content-Type-Options','nosniff');
      headers.set('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
      return new Response(response.body,{status:response.status,headers});
    }
    if(path.startsWith('/control/api/')) {
      if(!['GET','HEAD'].includes(request.method)&&request.headers.get('Origin')!==url.origin)return json({error:'Invalid origin'},403);
      if(path==='/control/api/login'&&request.method==='POST') {
        const ip=request.headers.get('CF-Connecting-IP')||'local';
        const attempt=await env.DB.prepare('SELECT * FROM auth_attempts WHERE ip=?').bind(ip).first();
        if(attempt?.until_time>now()&&attempt.attempts>=8)return json({error:'Too many attempts. Try again in 15 minutes.'},429);
        const {password}=await body(request,2000);
        if(!await equal(password,env.ADMIN_PASSWORD)) {
          await env.DB.prepare('INSERT INTO auth_attempts(ip,attempts,until_time) VALUES(?,1,?) ON CONFLICT(ip) DO UPDATE SET attempts=CASE WHEN until_time<? THEN 1 ELSE attempts+1 END,until_time=excluded.until_time').bind(ip,now()+900,now()).run();
          return json({error:'Incorrect dashboard password'},401);
        }
        await env.DB.prepare('DELETE FROM auth_attempts WHERE ip=? OR until_time<?').bind(ip,now()).run();
        const expiry=String(now()+86400),token=expiry+'.'+await sign(expiry,env.ADMIN_PASSWORD);
        return json({ok:true},200,{'Set-Cookie':`pc_control=${token}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=86400`});
      }
      if(!await loggedIn(request,env))return json({error:'Sign in to your dashboard'},401);
      if(path==='/control/api/logout'&&request.method==='POST')return json({ok:true},200,{'Set-Cookie':'pc_control=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0'});
      if(path==='/control/api/status'&&request.method==='GET') {
        const runtime=await read(env,'runtime'),snapshot=await read(env,'snapshot');
        const history=await env.DB.prepare('SELECT value,run_id FROM history ORDER BY updated DESC LIMIT 100').all();
        if(snapshot)snapshot.jobs=history.results.map(row=>({...JSON.parse(row.value),previous_session:row.run_id!==runtime?.run_id}));
        const last=await env.DB.prepare('SELECT * FROM starts ORDER BY requested DESC LIMIT 1').first();
        const missing=[];
        if(!env.GITHUB_TOKEN)missing.push('Cloudflare secret GITHUB_TOKEN');
        if(!/^[\w.-]+\/[\w.-]+$/.test(env.GITHUB_REPO||'')||env.GITHUB_REPO.startsWith('YOUR_'))missing.push('Cloudflare variable GITHUB_REPO');
        const stop=await read(env,'stop');
        return json({online:!!online(runtime),last_seen:runtime?.updated||null,snapshot,last_start:last,
          can_start:missing.length===0,missing_setup:missing,can_stop:!!online(runtime)&&runtime.protocol>=2,
          stop_requested:!!online(runtime)&&stop?.run_id===runtime?.run_id,
          notebook_url:env.KAGGLE_NOTEBOOK_URL,actions_url:`https://github.com/${env.GITHUB_REPO}/actions`});
      }
      if(path==='/control/api/stop'&&request.method==='POST') {
        const runtime=await read(env,'runtime');
        if(!online(runtime))return json({error:'No connected worker can receive a stop request. If Kaggle is still installing, cancel that run from Kaggle.'},409);
        if(runtime.protocol<2)return json({error:'This worker uses the older notebook. Import the updated notebook to enable dashboard Stop.'},409);
        await write(env,'stop',{run_id:runtime.run_id});
        return json({ok:true,message:'Stop requested. The worker will stop processing and export its backup, usually within about a minute. A batch run then completes; an interactive Kaggle allocation must still be stopped in Kaggle.'},202);
      }
      if(path==='/control/api/start'&&request.method==='POST') {
        if(online(await read(env,'runtime')))return json({error:'A Kaggle worker is already connected'},409);
        if(!env.GITHUB_TOKEN||!env.GITHUB_REPO||env.GITHUB_REPO.startsWith('YOUR_'))return json({error:'Configure the GitHub workflow, GITHUB_REPO and GITHUB_TOKEN first'},503);
        // A single conditional insert atomically prevents double-clicks and concurrent starts.
        const id=crypto.randomUUID();
        const result=await env.DB.prepare("INSERT INTO starts(id,requested,status) SELECT ?,?,'requested' WHERE NOT EXISTS(SELECT 1 FROM starts WHERE requested>? AND status='requested')").bind(id,now(),now()-1200).run();
        if(!result.meta.changes)return json({error:'A start was already requested. Check GitHub Actions; allow up to 20 minutes before retrying.'},409);
        const response=await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/start-kaggle.yml/dispatches`,{
          method:'POST',headers:{Authorization:'Bearer '+env.GITHUB_TOKEN,Accept:'application/vnd.github+json','User-Agent':'PeakCut-Control','X-GitHub-Api-Version':'2022-11-28'},
          body:JSON.stringify({ref:env.GITHUB_REF||'main'})});
        if(!response.ok) {await env.DB.prepare("UPDATE starts SET status='dispatch-failed' WHERE id=?").bind(id).run();return json({error:`GitHub rejected the start request (${response.status}). Check token permission and workflow filename.`},502);}
        return json({ok:true,message:'Run requested. GitHub submits the notebook; Kaggle allocates the runtime. Watch Actions until the heartbeat arrives.'},202);
      }
      return json({error:'Not found'},404);
    }
    if(path==='/')return Response.redirect(url.origin+'/control',302);
    // Platform fetches use upstream signed /pub/ links. All other routes require the dashboard login.
    if(!path.startsWith('/pub/')&&!await loggedIn(request,env))return Response.redirect(url.origin+'/control',302);
    const runtime=await read(env,'runtime');
    if(!online(runtime)||!validTunnel(runtime.tunnel_url))return new Response('PeakCut is offline. Open /control to start Kaggle. Saved progress remains available.',{status:503,headers:{'Content-Type':'text/plain','Cache-Control':'no-store'}});
    const target=new URL(path+url.search,runtime.tunnel_url);
    const headers=new Headers(request.headers);headers.delete('Host');
    headers.set('Cookie',(headers.get('Cookie')||'').split(';').filter(x=>!x.trim().startsWith('pc_control=')).join(';'));
    const response=await fetch(target,{method:request.method,headers,body:['GET','HEAD'].includes(request.method)?undefined:request.body,redirect:'manual'});
    const out=new Headers(response.headers);out.set('Cache-Control','no-store');
    const location=out.get('Location');
    if(location?.startsWith(runtime.tunnel_url))out.set('Location',url.origin+location.slice(runtime.tunnel_url.length));
    return new Response(response.body,{status:response.status,headers:out});
  } catch(error) {return json({error:'Request failed. Check Worker logs and the configuration; no action has been confirmed.'},500);}
}};
