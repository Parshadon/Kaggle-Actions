import ast
import json
import shutil
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE.parents[1] / 'outputs'
OUT.mkdir(exist_ok=True)
adapters = {name: (BASE/name).read_text(encoding='utf-8') for name in ('owner_app.py', 'bridge.py', 'state_io.py')}
runtime = (BASE/'runtime.py').read_text(encoding='utf-8')
cells=[]
def md(text): cells.append({'cell_type':'markdown','metadata':{},'source':text.splitlines(True)})
def code(text):
    ast.parse(text)
    cells.append({'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':text.splitlines(True)})

md('''# PeakCut Studio — Kaggle worker

Run the real PeakCut application behind your permanent Cloudflare dashboard.
**First deploy the dashboard using the setup guide.** Select **GPU T4 ×2**, enable Internet, and keep this notebook private.

Add and enable these Kaggle Secrets under Add-ons → Secrets:
- `PEAKCUT_OWNER_EMAIL`: your PeakCut login email.
- `PEAKCUT_OWNER_PASSWORD`: a password of at least 12 characters.
- `PEAKCUT_BRIDGE_TOKEN`: the same random 32+ character secret configured as `BRIDGE_TOKEN` in Cloudflare.

The notebook does not train a new model. It runs pinned PeakCut code with local speech recognition and optional Ollama.
GPU speech recognition is probed; if unavailable it falls back to CPU. English and Arabic are the upstream languages.
Setup downloads several GB on the first run. No paid AI API is required. Kaggle quotas and runtime limits still apply.
''')
md('''## 1. Configure
Paste your permanent dashboard origin below. The dashboard is at `/control`; the full PeakCut editor is at `/app`.
Start with one short, uploaded English video to verify the pipeline before trying YouTube or live streams.
''')
code('''DASHBOARD_URL = "https://YOUR-WORKER.YOUR-SUBDOMAIN.workers.dev"
SESSION_MINUTES = 120
USE_GPU_ASR = True
USE_LOCAL_AI = True
# Optional: attach your prior encrypted backup as a PRIVATE Kaggle dataset.
RESTORE_BACKUP = ""  # e.g. /kaggle/input/my-private-backup/peakcut-state.enc
''')
md('## 2. Load the launcher\nThis writes no credentials into the notebook or saved output.')
code('ADAPTERS = '+repr(adapters)+'\n'+runtime)
md('## 3. Install and check speech recognition\nWatch the cell output for installation and model-download progress.')
code('''if "YOUR-" in DASHBOARD_URL:
    raise ValueError("Set DASHBOARD_URL in cell 1 before installing.")
if not 10 <= SESSION_MINUTES <= 240:
    raise ValueError("Choose a session between 10 and 240 minutes.")
py, peakcut_env, gpu_count = setup(USE_GPU_ASR, globals().get("RESTORE_BACKUP", ""))
print("Speech backend:", peakcut_env.get("PEAKCUT_ASR_PROVIDER", "cpu"))
''')
md('''## 4. Local AI for clip selection
The second GPU is assigned to Ollama when present. GPU 0 is assigned to speech recognition.
The small local model is a practical free starting point; it does not guarantee viral clip selection.
If disabled, PeakCut uses its loudness-based fallback with no AI-written titles.
''')
code('''if USE_LOCAL_AI:
    local_ai(py, peakcut_env, gpu_count)
else:
    peakcut_env.update(PEAKCUT_AI_PROVIDER="ollama", PEAKCUT_AI_MODELS="")
    (DATA / "ai.json").write_text(json.dumps({"provider":"ollama","models":[],"base_url":"http://127.0.0.1:11434/v1","key":""}))
print("Clip-selection setup finished.")
''')
md('''## 5. Open your dashboard
Open the displayed link, enter your Cloudflare dashboard password, then open the full editor.
Sign in there with your **PeakCut owner email/password**. Paste your video link in New video, or upload a file.
Use the permanent dashboard to see progress; use PeakCut for previews, caption options, accounts and publishing.
''')
code('''bridge_thread = start(py, peakcut_env, DASHBOARD_URL)
from IPython.display import display, HTML
import html
display(HTML('<a target="_blank" rel="noopener" href="'+html.escape(DASHBOARD_URL+'/control', quote=True)+'" style="display:inline-block;background:#6f4ce8;color:white;padding:18px 28px;border-radius:12px;font-size:20px;text-decoration:none">Open PeakCut dashboard</a>'))
''')
md('''## 6. Run the bounded processing session
Leave this cell running while using the dashboard. For a batch run, Save & Run All keeps the requested computation running without this browser tab.
It stops after the configured duration; this is not an unlimited service or an automatic restart system.
Completed clips are copied to `/kaggle/working/peakcut-exports` every 30 seconds.
Stopping abruptly can interrupt an edit or upload. The encrypted settings backup is made on orderly shutdown.
''')
code('''deadline = time.monotonic() + SESSION_MINUTES * 60
try:
    while time.monotonic() < deadline and not STOP.is_set():
        if not bridge_thread.is_alive() and not STOP.is_set():
            raise RuntimeError("Progress bridge stopped. Check the diagnostics cell.")
        if any(p.poll() is not None for p in PROCESSES):
            raise RuntimeError("A service stopped. Check the diagnostics cell.")
        copied = export_clips()
        if copied:
            print(f"Saved {copied} completed clip(s) to notebook outputs.", flush=True)
        time.sleep(30)
finally:
    shutdown()
''')
md('''## Diagnostics — run when needed
Logs are local to this notebook. Do not share raw logs if you have connected private accounts.
''')
code('''for name in ("server", "ollama", "tunnel"):
    path = Path("/tmp/peakcut-" + name + ".log")
    if path.exists():
        print("\\n" + name.upper())
        text = path.read_text(errors="replace")[-4000:]
        text = re.sub(r"https?://[^\\s]+", "[URL]", text)
        print(text)
''')
md('''## Stop manually
Run only when you want to stop. Download the exported MP4s and `peakcut-state.enc` before discarding the session.
The encrypted backup contains accounts/settings/history, **not video files**. Restore it with the same owner password.
Uploaded source files and unfinished renders are not automatically recoverable. Saved Cloudflare history is separate.
''')
code('shutdown()')

notebook={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python'},'kaggle':{'isInternetEnabled':True,'isGpuEnabled':True}},'cells':cells}
for i,c in enumerate(cells): c['id']=f'peakcut-{i:02d}'
name='PeakCut - Kaggle Studio.ipynb'
(OUT/name).write_text(json.dumps(notebook,ensure_ascii=False,indent=1),encoding='utf-8')
shutil.copy2(OUT/name, BASE/name)
shutil.copy2(BASE/'SETUP.md',OUT/'PeakCut - Setup Guide.md')
with zipfile.ZipFile(OUT/'PeakCut - Kaggle and Web Dashboard.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for directory in ('dashboard','.github'):
        for f in (BASE/directory).rglob('*'):
            if f.is_file() and 'node_modules' not in f.parts and '.wrangler' not in f.parts and 'package-lock' not in f.name:
                archive.write(f,f.relative_to(BASE))
    for filename in ('SETUP.md',name,'runtime.py','owner_app.py','bridge.py','state_io.py','build.py','test_adapter.py'):
        archive.write(BASE/filename,filename)
print('Built notebook, deployment ZIP, and setup guide in',OUT)
with zipfile.ZipFile(OUT/'PeakCut - Dashboard Controls Update.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for f in [BASE/'dashboard/worker.mjs',*(BASE/'dashboard/public').rglob('*')]:
        if f.is_file(): archive.write(f,f.relative_to(BASE/'dashboard'))
