"""Send allowlisted progress, never social tokens, to the permanent dashboard."""
import os
import time
import requests


def sanitize_jobs(rows):
    result = []
    for row in rows[:100]:
        item = {k: row.get(k) for k in ('id', 'title', 'status', 'stage', 'duration', 'error')}
        item['clips'] = [{k: c.get(k) for k in ('id', 'title', 'status', 'start', 'end')} for c in row.get('clips', [])[:20]]
        result.append(item)
    return result


def run(stop, public_url, tunnel_url, run_id):
    local = requests.Session()
    # HTTPS cookie is deliberately supplied explicitly for loopback requests only.
    response = local.post('http://127.0.0.1:8765/api/auth/login', json={
        'email': os.environ['PEAKCUT_OWNER_EMAIL'], 'password': os.environ['PEAKCUT_OWNER_PASSWORD']},
        headers={'Origin': public_url}, timeout=20)
    response.raise_for_status()
    cookie = response.cookies.get('peakcut_session')
    if not cookie:
        raise RuntimeError('PeakCut login did not return a session cookie')
    headers = {'Cookie': 'peakcut_session=' + cookie}
    errors = 0
    while not stop.is_set():
        try:
            jobs = local.get('http://127.0.0.1:8765/api/jobs', headers=headers, timeout=20)
            jobs.raise_for_status()
            accounts = local.get('http://127.0.0.1:8765/api/accounts', headers=headers, timeout=20)
            accounts.raise_for_status()
            posting = local.get('http://127.0.0.1:8765/api/overview', headers=headers, timeout=20)
            # Posting summary is read separately; no account payload is forwarded wholesale.
            overview = posting.json() if posting.ok else {}
            payload = {'run_id': run_id, 'protocol': 2, 'tunnel_url': tunnel_url, 'jobs': sanitize_jobs(jobs.json()),
                       'accounts': [{k: a.get(k) for k in ('id', 'platform', 'name')} for a in accounts.json()],
                       'posting': {'posts': [{k: p.get(k) for k in ('id', 'platform', 'status', 'due_at', 'posted_at', 'error')}
                                             for p in overview.get('posts', [])[:100]],
                                   'recording': overview.get('recording', 0), 'paused': overview.get('paused', False)}, 'online': True}
            # The overview is public upstream state; the receiver also limits its size.
            out = requests.post(public_url + '/bridge/heartbeat', json=payload,
                headers={'Authorization': 'Bearer ' + os.environ['PEAKCUT_BRIDGE_TOKEN']}, timeout=25)
            out.raise_for_status()
            if out.json().get('stop_requested'):
                print('Stop requested from the dashboard. Ending the processing session.', flush=True)
                stop.set()
            errors = 0
        except Exception as exc:
            errors += 1
            print('Dashboard heartbeat failed:', type(exc).__name__, '(retrying)', flush=True)
        stop.wait(min(60, 20 + errors * 5))
    try:
        requests.post(public_url + '/bridge/offline', json={'run_id': run_id},
            headers={'Authorization': 'Bearer ' + os.environ['PEAKCUT_BRIDGE_TOKEN']}, timeout=15)
    except requests.RequestException:
        pass
