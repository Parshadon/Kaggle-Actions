const $=id=>document.getElementById(id);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let busy=false;
async function api(path,body){const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const result=await response.json().catch(()=>({error:'Service unavailable'}));if(!response.ok)throw Object.assign(new Error(result.error||result.detail||'Request failed'),{status:response.status});return result;}
function notice(text){$('notice').textContent=text;}
function safeLink(id,url){try{const u=new URL(url);if(u.protocol==='https:')$(id).href=u.href;}catch{}}
async function refresh(){
 try{const state=await api('/control/api/status');$('login').hidden=true;$('workspace').hidden=false;
 $('connection').textContent=state.online?'Worker online':'Worker offline';$('dot').classList.toggle('online',state.online);
 $('start').disabled=busy||state.online||!state.can_start;
 $('stop').disabled=busy||!state.can_stop||state.stop_requested;
 $('stop').textContent=state.stop_requested?'Stopping…':'Stop processing';
 $('setup-status').textContent=state.can_start?'Start settings present':'Start needs setup';
 $('setup-detail').textContent=state.missing_setup?.length?'Start is unavailable. Missing: '+state.missing_setup.join(', ')+'. Expand the setup steps below.': 'Start requests a new Kaggle batch run through GitHub Actions. '+(state.online&&!state.can_stop?'This connected worker uses the older notebook; update it to enable Stop.':'');
 $('session-title').textContent=state.online?'Your studio is ready':'Waiting for a worker';
 $('session-detail').textContent=state.online?'Open the editor to review, edit and publish your clips.':state.last_start?.status==='requested'?'Session requested. Check startup logs; Kaggle allocation and model setup take time.':'Start a session or run your notebook manually. Saved progress is shown below.';
 safeLink('kaggle',state.notebook_url);safeLink('actions',state.actions_url);
 $('generate').disabled=!state.online;
 const snap=state.snapshot||{},jobs=snap.jobs||[],accounts=snap.accounts||[],posts=snap.posting?.posts||[];
 $('project-count').textContent=jobs.length;$('clip-count').textContent=jobs.flatMap(j=>j.clips||[]).filter(c=>c.status==='done').length;
 $('post-count').textContent=posts.filter(p=>!['posted','failed','cancelled'].includes(p.status)).length;$('account-count').textContent=accounts.length;
 $('synced').textContent=snap.updated?'Synced '+new Date(snap.updated*1000).toLocaleTimeString():'No snapshot yet';
 $('jobs').innerHTML=jobs.length?jobs.map(j=>`<article class="job"><div><h3>${esc(j.title||j.id)}</h3><p>${j.previous_session?'Previous session · ':''}${esc(j.stage||j.status)} · ${(j.clips||[]).filter(c=>c.status==='done').length} clips ready</p>${j.error?`<p>${esc(j.error)}</p>`:''}</div><div><span class="badge">${esc(j.status)}</span></div></article>`).join(''):'<div class="empty">Your next great clip starts here.<br>Connect a Kaggle session and add your first video.</div>';
 $('accounts').innerHTML=accounts.length?accounts.map(a=>`<div class="account"><span>${esc(a.name)}</span><span class="badge">${esc(a.platform)}</span></div>`).join(''):'<p class="muted">No accounts synced yet.</p>';
 $('posts').innerHTML=posts.length?posts.map(p=>`<div class="post"><span>${esc(p.platform||p.id)}</span><span class="badge">${esc(p.status)}</span></div>`).join(''):'<p class="muted">Publishing activity appears here after you queue a clip in PeakCut.</p>';
 }catch(error){if(error.status===401){$('login').hidden=false;$('workspace').hidden=true;$('connection').textContent='Private workspace';}else notice(error.message);}
}
$('login-form').onsubmit=async event=>{event.preventDefault();try{await api('/control/api/login',{password:$('password').value});$('password').value='';$('login-error').textContent='';await refresh();}catch(error){$('login-error').textContent=error.message;}};
$('logout').onclick=async()=>{await api('/control/api/logout',{});await refresh();};
$('mobile-logout').onclick=$('logout').onclick;
$('start').onclick=async()=>{busy=true;$('start').disabled=true;try{const result=await api('/control/api/start',{});notice(result.message);}catch(error){notice(error.message);}finally{busy=false;await refresh();}};
$('stop').onclick=async()=>{if(!confirm('Stop processing? An active render or upload may be interrupted. Finished clips and settings will be exported when shutdown succeeds.'))return;busy=true;try{const result=await api('/control/api/stop',{});notice(result.message);}catch(error){notice(error.message);}finally{busy=false;await refresh();}};
$('create-form').onsubmit=async event=>{event.preventDefault();$('generate').disabled=true;try{const [min_len,max_len]=$('length').value.split(',').map(Number);await api('/api/jobs',{url:$('video-url').value,options:{min_len,max_len,max_clips:Number($('count').value),quality:Number($('quality').value),captions:true}});notice('Project queued. Progress will appear after the next sync.');$('video-url').value='';}catch(error){notice(error.status===401?'Open the full editor and sign in with your PeakCut owner account first. Then return here.':error.message);}finally{await refresh();}};
refresh();setInterval(()=>{if(!document.hidden)refresh();},20000);
