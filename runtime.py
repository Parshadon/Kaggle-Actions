"""Kaggle launcher. Executed from the generated notebook; no runtime installation on Windows."""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
import requests

COMMIT = '39c32a878648619e981b57af608ba4571a82247f'
ROOT = Path('/tmp/peakcut')
ENV = Path('/tmp/peakcut-env')
DATA = Path('/tmp/peakcut-data')
OUTPUT = Path('/kaggle/working/peakcut-exports')
PROCESSES = []
STOP = threading.Event()


def command(args, **kwargs):
    subprocess.run([str(x) for x in args], check=True, **kwargs)


def secret(name, required=True):
    value = os.environ.get(name, '')
    if not value:
        try:
            from kaggle_secrets import UserSecretsClient
            value = UserSecretsClient().get_secret(name)
        except Exception:
            pass
    if required and not value:
        raise RuntimeError(f'Add and enable Kaggle Secret {name}, then rerun. Never paste it in notebook output.')
    return value


def download(url, dest):
    dest = Path(dest)
    part = dest.with_suffix('.part')
    with requests.get(url, stream=True, timeout=(30, 120)) as response:
        response.raise_for_status()
        with part.open('wb') as f:
            for chunk in response.iter_content(1024 * 1024):
                f.write(chunk)
    part.replace(dest)


def launch(args, name, env):
    log = Path('/tmp') / ('peakcut-' + name + '.log')
    with log.open('w') as f:
        process = subprocess.Popen([str(a) for a in args], cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    PROCESSES.append(process)
    return process, log


def wait_http(url, process, seconds=120):
    for _ in range(seconds):
        if process.poll() is not None:
            raise RuntimeError('A service exited. Read the diagnostic log cell.')
        try:
            if requests.get(url, timeout=2).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise TimeoutError('Service startup timed out: ' + url)


def setup(use_gpu_asr=True, restore_backup=''):
    if not Path('/kaggle').exists():
        raise RuntimeError('Run this notebook in Kaggle, not on your Windows computer.')
    if PROCESSES and any(p.poll() is None for p in PROCESSES):
        raise RuntimeError('Stop the previous session before rerunning setup.')
    for key in ('PEAKCUT_OWNER_EMAIL', 'PEAKCUT_OWNER_PASSWORD', 'PEAKCUT_BRIDGE_TOKEN'):
        os.environ[key] = secret(key)
    if len(os.environ['PEAKCUT_OWNER_PASSWORD']) < 12:
        raise ValueError('Set an owner password with at least 12 characters.')
    if len(os.environ['PEAKCUT_BRIDGE_TOKEN']) < 32:
        raise ValueError('Use at least 32 random characters for the bridge token.')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    command(['apt-get', 'update', '-qq'])
    command(['apt-get', 'install', '-y', '-qq', 'ffmpeg', 'git', 'zstd'])
    if not ROOT.exists():
        command(['git', 'clone', '--no-checkout', 'https://github.com/haziqahmedqasmi/PeakCut.git', ROOT])
    command(['git', '-C', ROOT, 'checkout', '--detach', COMMIT])
    try:
        command([sys.executable, '-m', 'venv', ENV])
    except subprocess.CalledProcessError:
        print('Built-in venv/ensurepip failed; using virtualenv bootstrap instead.', flush=True)
        bootstrap = Path('/tmp/peakcut-virtualenv.pyz')
        download('https://bootstrap.pypa.io/virtualenv.pyz', bootstrap)
        command([sys.executable, bootstrap, '--python', sys.executable, ENV])
    py = ENV / 'bin/python'
    command([py, '-m', 'pip', 'install', '-q', '--upgrade', 'pip'])
    command([py, '-m', 'pip', 'install', '-q', '-r', ROOT / 'requirements.txt', 'requests', 'cryptography', 'deno', 'wrapt'])
    (ROOT / 'state_io.py').write_text(ADAPTERS['state_io.py'], encoding='utf-8')
    if restore_backup:
        command([py, ROOT / 'state_io.py', 'restore', restore_backup, DATA], env=dict(os.environ))
        print('Restored encrypted account settings and history. Media must be restored separately if needed.')
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], capture_output=True, text=True) if shutil.which('nvidia-smi') else None
    names = gpu.stdout.strip().splitlines() if gpu and gpu.returncode == 0 else []
    print('CPU cores:', os.cpu_count(), '| GPUs:', ', '.join(names) or 'none', flush=True)
    env = dict(os.environ, PEAKCUT_DATA=str(DATA), PEAKCUT_MODELS='/tmp/peakcut-models', PEAKCUT_HOST='127.0.0.1',
               PEAKCUT_PORT='8765', PEAKCUT_ACCOUNTS='1', PEAKCUT_UPDATE_CHECK='0', PEAKCUT_FETCH_MODEL='0',
               PEAKCUT_JOB_WORKERS='1', PEAKCUT_MAX_LIVE='1', PEAKCUT_MAX_LIVE_HOURS='2',
               PEAKCUT_MAX_USER_GB='12', PEAKCUT_ASR_THREADS='2', PEAKCUT_ASR_COPIES='1',
               PYTHONUNBUFFERED='1', PATH=str(ENV / 'bin') + ':' + os.environ['PATH'])
    if names and use_gpu_asr:
        print('Installing the upstream CUDA speech-recognition build…', flush=True)
        result = subprocess.run([str(py), '-m', 'pip', 'install', '-q',
            'sherpa-onnx==2.0.1+cuda12.cudnn9.onnxruntime1.28.2', '-f', 'https://k2-fsa.github.io/sherpa/onnx/cuda.html',
            'nvidia-cublas-cu12', 'nvidia-cudnn-cu12>=9,<10', 'nvidia-cufft-cu12', 'nvidia-curand-cu12',
            'nvidia-cuda-runtime-cu12', 'nvidia-cuda-nvrtc-cu12', 'nvidia-nvjitlink-cu12'])
        if result.returncode == 0:
            libraries = list(ENV.glob('lib/python*/site-packages/nvidia/*/lib'))
            env.update(LD_LIBRARY_PATH=':'.join(map(str, libraries)) + ':' + env.get('LD_LIBRARY_PATH', ''),
                       CUDA_VISIBLE_DEVICES='0', PEAKCUT_ASR_PROVIDER='cuda',
                       PEAKCUT_ASR_MODEL='sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-fp16')
        else:
            print('CUDA wheel unavailable for this Python version; restoring CPU speech recognition.', flush=True)
            command([py, '-m', 'pip', 'install', '-q', '--force-reinstall', 'sherpa-onnx==2.0.1'])
    print('Downloading and checking the English speech model. First setup can take several minutes.', flush=True)
    probe = 'from studio import fetch_model,transcribe; import numpy as np; fetch_model.ensure(); transcribe.decode_pieces([np.zeros(16000,dtype=np.float32)]); print("Speech model ready")'
    try:
        command([py, '-c', probe], cwd=ROOT, env=env, timeout=1200)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        if env.get('PEAKCUT_ASR_PROVIDER') != 'cuda':
            raise
        print('CUDA speech probe failed. Retrying the tested upstream CPU path.', flush=True)
        env.update(PEAKCUT_ASR_PROVIDER='cpu', PEAKCUT_ASR_MODEL='sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8')
        command([py, '-c', probe], cwd=ROOT, env=env, timeout=1200)
    return py, env, len(names)


def local_ai(py, env, gpu_count, model='qwen2.5:3b'):
    print('Installing Ollama and downloading the local AI model…', flush=True)
    target = Path('/tmp/peakcut-ollama')
    target.mkdir(exist_ok=True)
    binary = target / 'bin/ollama'
    if not binary.exists():
        archive = Path('/tmp/peakcut-ollama.tar.zst')
        download('https://github.com/ollama/ollama/releases/download/v0.40.17/ollama-linux-amd64.tar.zst', archive)
        command(['tar', '--zstd', '-xf', archive, '-C', target])
        archive.unlink()
    ai_env = dict(env, OLLAMA_HOST='127.0.0.1:11434', OLLAMA_MODELS='/tmp/peakcut-llm-models',
                  OLLAMA_NUM_PARALLEL='1', OLLAMA_CONTEXT_LENGTH='8192', OLLAMA_KEEP_ALIVE='10m',
                  CUDA_VISIBLE_DEVICES='1' if gpu_count > 1 else '0')
    process, _ = launch([binary, 'serve'], 'ollama', ai_env)
    wait_http('http://127.0.0.1:11434/api/tags', process)
    command([binary, 'pull', model], env=ai_env, timeout=1800)
    env.update(PEAKCUT_AI_PROVIDER='ollama', PEAKCUT_AI_MODELS=model, PEAKCUT_AI_BASE_URL='http://127.0.0.1:11434/v1')
    # Upstream settings override environment variables. Keep this notebook explicitly local/free.
    (DATA / 'ai.json').write_text(json.dumps({'provider':'ollama','models':[model],
        'base_url':'http://127.0.0.1:11434/v1','key':''}))


def start(py, env, dashboard_url):
    if not re.fullmatch(r'https://[A-Za-z0-9.-]+', dashboard_url):
        raise ValueError('Enter your deployed dashboard HTTPS origin, without a path or trailing slash.')
    env['PEAKCUT_PUBLIC_URL'] = dashboard_url
    for name in ('owner_app.py', 'bridge.py'):
        (ROOT / name).write_text(ADAPTERS[name], encoding='utf-8')
    server, _ = launch([py, ROOT / 'owner_app.py'], 'server', env)
    wait_http('http://127.0.0.1:8765/healthz', server)
    binary = Path('/tmp/peakcut-cloudflared')
    if not binary.exists():
        download('https://github.com/cloudflare/cloudflared/releases/download/2026.11.2/cloudflared-linux-amd64', binary)
        binary.chmod(0o700)
    tunnel, log = launch([binary, 'tunnel', '--no-autoupdate', '--protocol', 'http2', '--url', 'http://127.0.0.1:8765'], 'tunnel', env)
    tunnel_url = None
    for _ in range(90):
        found = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', log.read_text(errors='replace'))
        if found:
            tunnel_url = found.group(0)
            break
        if tunnel.poll() is not None:
            break
        time.sleep(1)
    if not tunnel_url:
        raise RuntimeError('Tunnel could not start; see diagnostics. Kaggle networking may restrict it.')
    # Do not display the temporary origin. The permanent Worker origin proxies PeakCut.
    sys.path.insert(0, str(ROOT))
    import bridge
    STOP.clear()
    thread = threading.Thread(target=bridge.run, args=(STOP, dashboard_url, tunnel_url, uuid.uuid4().hex), daemon=True)
    thread.start()
    print('Dashboard: ' + dashboard_url + '/control', flush=True)
    print('PeakCut editor: ' + dashboard_url + '/app', flush=True)
    print('Sign in with your PEAKCUT_OWNER_EMAIL and PEAKCUT_OWNER_PASSWORD. Paste the video link in New video.', flush=True)
    return thread


def export_clips():
    count = 0
    for record in DATA.glob('users/**/job.json'):
        try:
            job = json.loads(record.read_text())
        except (OSError, ValueError):
            continue
        for clip in job.get('clips', []):
            if clip.get('status') != 'done' or not clip.get('file'):
                continue
            source = record.parent / 'clips' / Path(clip['file']).name
            if not source.is_file():
                continue
            dest = OUTPUT / source.relative_to(DATA)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or source.stat().st_mtime > dest.stat().st_mtime:
                staging = dest.with_suffix('.part')
                shutil.copy2(source, staging)
                staging.replace(dest)
                count += 1
    return count


def shutdown():
    STOP.set()
    time.sleep(2)
    import signal
    for process in reversed(PROCESSES):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
    export_clips()
    py = ENV / 'bin/python'
    if py.exists() and (ROOT / 'state_io.py').exists() and (DATA / 'peakcut.db').exists():
        command([py, ROOT / 'state_io.py', 'backup', DATA, OUTPUT / 'peakcut-state.enc'])
        print('Encrypted settings backup saved. Restore with the SAME owner password in a later notebook session.')
    print('Services stopped. Save/download /kaggle/working/peakcut-exports before ending the session.')
