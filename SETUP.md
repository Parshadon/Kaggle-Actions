# PeakCut Studio: Kaggle + permanent web dashboard

This package contains a Kaggle notebook, a Cloudflare Workers web dashboard, a D1 schema, and a GitHub Actions workflow that submits a Kaggle GPU notebook run. You can access the deployed dashboard from a phone or computer without leaving your Windows computer switched on.

**The package is built, not deployed to your accounts.** Cloudflare, GitHub and Kaggle account setup is still required. No credentials are included. A real Kaggle GPU run and live social publishing have not been tested in your account.

## What runs where

### Dashboard controls update

The updated dashboard explains missing Start configuration and links directly to `/app/settings/apps`.
`Stop processing` sends a run-specific stop request to the updated notebook. It is not a force-cancel API for an unresponsive Kaggle session or for startup before the worker connects. In batch mode the notebook stops its services, exports a backup and finishes. In interactive mode, stop the allocation in Kaggle afterwards. An active render/upload may be interrupted; verify publishing status before retrying an uncertain upload.

For an existing deployment: extract `PeakCut - Dashboard Controls Update.zip` into the existing `dashboard` folder, replacing `worker.mjs` and `public/` files. Your `wrangler.jsonc`, database ID and secrets are not included in that update ZIP and stay unchanged. Run `npm.cmd run deploy`. Import the updated notebook on the next Kaggle run to enable Stop. No database migration is needed.

Start remains unavailable until GitHub Actions, the Kaggle API token, kernel ID, dashboard URL and the Cloudflare GitHub token/repository are configured as described below. Installing this update does not configure those accounts automatically.

| Component | Location |
|---|---|
| Permanent dashboard, login, saved progress/history | Cloudflare Workers + D1 |
| Request to start a Kaggle run | Dashboard → GitHub Actions → official Kaggle CLI |
| Speech recognition, clip selection, editing, publishing | PeakCut inside an active Kaggle session |
| Full PeakCut interface | Proxied through the same permanent dashboard origin at `/app` |
| Finished video files | Kaggle notebook outputs; download/save before discarding a session |
| Account settings and internal history backup | Password-encrypted `peakcut-state.enc`, exported on orderly shutdown |

The default session is 120 minutes, configurable to 10–240 minutes in the notebook. It does not auto-renew sessions, bypass quotas, or promise 24/7 GPU availability. The dashboard stays available while Kaggle is off, but editing, previews, account connections and posting need the worker online. This is a single-owner setup with one active Kaggle worker.

The permanent web app uses **Workers**, not a static Pages upload: it needs authenticated server routes, a database and a streaming reverse proxy. The architecture is intended to fit free allowances for light personal use; usage limits still apply. The temporary Cloudflare Quick Tunnel is a development connector, not a production availability guarantee. If Kaggle blocks its networking, the notebook reports a startup failure rather than claiming to be connected.

## 1. Deploy the web dashboard once

You need a Cloudflare account and Node.js on the machine you use for this one-time deployment. Your computer can be switched off afterwards.

1. Extract the ZIP. Open a terminal inside its `dashboard` folder.
2. Run:

```text
npm install
npx wrangler login
npx wrangler d1 create peakcut-control
```

3. Copy the returned database ID into `dashboard/wrangler.jsonc`, replacing `REPLACE_WITH_YOUR_D1_DATABASE_ID`.
4. In that file, replace `GITHUB_REPO` with `your-github-name/your-repository`. You may leave this for later if starting Kaggle manually first.
5. Initialize the database:

```text
npx wrangler d1 execute peakcut-control --remote --file=schema.sql
```

6. Add secrets through these prompts. Do not put them in the JSON configuration or commit them to GitHub:

```text
npx wrangler secret put ADMIN_PASSWORD
npx wrangler secret put BRIDGE_TOKEN
```

`ADMIN_PASSWORD` is the dashboard login password (12+ characters). `BRIDGE_TOKEN` is a random secret of at least 32 characters. Generate a random value in a password manager and keep a copy: Kaggle needs the same value under a different secret name, `PEAKCUT_BRIDGE_TOKEN`.

7. Deploy:

```text
npm run deploy
```

Wrangler prints your real HTTPS address, for example `https://peakcut-studio.your-subdomain.workers.dev`. Open that address with `/control` appended. It should show the private login screen. After login, **Worker offline** is correct until the notebook connects.

Keep the origin unchanged after registering social OAuth callbacks. Both `/control` and `/app` use this same origin. A custom domain is optional.

## 2. Start Kaggle manually first

1. Create a **private** Kaggle notebook and import `PeakCut - Kaggle Studio.ipynb`.
2. Enable **Internet** and select **GPU T4 ×2** if available. Kaggle documents approximately 29 GB RAM and 4 CPU cores for this environment; 330 GB/96 cores refers to its separate TPU environment.
3. Under **Add-ons → Secrets**, create and enable access to:

| Kaggle secret | Value |
|---|---|
| `PEAKCUT_OWNER_EMAIL` | An email-shaped login name you will use for PeakCut |
| `PEAKCUT_OWNER_PASSWORD` | A strong password, at least 12 characters |
| `PEAKCUT_BRIDGE_TOKEN` | Exactly the Cloudflare `BRIDGE_TOKEN` value |

The dashboard password and PeakCut owner password are separate logins. No email delivery is configured; keep the owner password safely.

4. In the first configuration cell, replace `DASHBOARD_URL` with your deployed HTTPS origin, without `/control` and without a trailing slash.
5. Run cells in order. The first run downloads dependencies and models; it is not a clip-generation benchmark. Installation and model probes print progress in the notebook.
6. After the **Open PeakCut dashboard** link appears, open it. Wait for the status heartbeat (about 20 seconds).
7. Click **Open full editor**, then sign in with the owner email/password from your Kaggle Secrets.
8. Paste a video link in **New video**, or upload a small video to test first. The permanent control page also has a link-input form after you have signed in to PeakCut.
9. Keep the bounded-session cell running. Download finished clips from PeakCut, or from the notebook's `peakcut-exports` outputs.

The dashboard has 30–60 second and 60–120 second presets, clip-count controls, and 720p/1080p options. Full PeakCut provides its original captions, layouts, live-channel settings, previews, creator workspaces and posting rules. This is the actual upstream editor, not a simulated editor UI.

## 3. Enable the dashboard's Start Kaggle session button

This uses official `kaggle kernels push --accelerator NvidiaTeslaT4`. It requests a **new batch run**. It does not resume an interactive tab. Kaggle can queue or reject it based on quota, verification, availability or account permissions.

1. Create a GitHub repository and upload the extracted package contents at its root, including the hidden `.github/workflows/start-kaggle.yml` and the notebook. A private repository is appropriate; Actions has its own free usage allowance.
2. Use the **same private Kaggle notebook** you tested above. Enable its three Secrets before using the API workflow.
3. In GitHub → repository Settings → Secrets and variables → Actions, add:

| Type | Name | Value |
|---|---|---|
| Secret | `KAGGLE_API_TOKEN` | Your Kaggle API token from Kaggle account settings |
| Variable | `KAGGLE_KERNEL_ID` | `your-kaggle-name/notebook-slug` |
| Variable | `DASHBOARD_URL` | Your deployed Worker HTTPS origin |

4. Create a GitHub fine-grained token restricted to this repository with **Actions: read/write** and required metadata access. Add it to Cloudflare using:

```text
npx wrangler secret put GITHUB_TOKEN
```

5. Confirm `GITHUB_REPO` and `GITHUB_REF` in `wrangler.jsonc` are correct. Set `KAGGLE_NOTEBOOK_URL` to the actual notebook URL. Redeploy with `npm run deploy`.
6. Stop your manual Kaggle session before requesting another. Sign into `/control` and click **Start Kaggle session** once. **View startup logs** opens GitHub Actions. A successful GitHub submission is not proof that the notebook finished installing: wait for **Worker online**.

The start endpoint prevents duplicate clicks for 20 minutes. If it fails, check the existing GitHub/Kaggle run before trying again. Do not repeatedly consume quota by starting overlapping runs. If an API-created version cannot access the attached Kaggle Secrets, enable them on that notebook and test manually; the launcher fails before downloading models when a required secret is missing.

You can use manual Kaggle startup without GitHub Actions. The Start button is disabled until the GitHub token is configured.

## 4. Connect social media accounts

Once the worker is online, open PeakCut → **Settings → Connected apps**. Follow the upstream setup panel to register your developer app and copy the callback URL. Use your permanent dashboard origin, not the temporary connector URL.

- **YouTube:** configure a Google OAuth web client and enable YouTube Data API. Platform audit/verification restrictions can affect public uploads.
- **Instagram:** supported Creator/Business account and Meta developer-app configuration are required. Instagram downloads the clip through the signed public `/pub/` endpoint while the worker is online.
- **TikTok:** configure Login Kit and Content Posting API; platform approval can restrict public posting.
- **Facebook:** not implemented by the pinned PeakCut release. This package does not pretend to add it.

Review a rendered clip and choose its destination accounts in PeakCut to post. Creator posting rules allow automatic publishing with spacing/caps. No clip is automatically published just by starting this notebook; explicitly configure your posting rules. The permanent dashboard displays the latest synced publishing state, not a separate publishing engine.

No social accounts have been connected or posts sent as part of creating this package.

## 5. Save clips, restore accounts and retain history

The dashboard stores job metadata/history in D1. The visible list shows the latest 100 records. This is not permanent video storage. A previous session's status is historical, not proof its old process is still running.

The notebook copies completed MP4 clips to `/kaggle/working/peakcut-exports`. On an orderly stop it also writes **`peakcut-state.enc`**: an authenticated encrypted backup of the PeakCut database and JSON metadata, including account credentials. It uses a key derived from your owner password. Neither plaintext secrets nor the database are exported to the notebook's output folder.

Download/save the output before discarding the runtime. Hard termination may prevent the newest backup from being written. Keep the notebook and any dataset containing the backup private even though the backup is encrypted.

For a later manual session:

1. Add the saved encrypted backup as a private Kaggle dataset input.
2. Use the **same owner email/password** in Kaggle Secrets.
3. Set `RESTORE_BACKUP` to its `/kaggle/input/.../peakcut-state.enc` path before setup.
4. Start with a fresh runtime. The restore refuses to overwrite an existing database.

For dashboard-triggered runs, also set GitHub Actions variables `KAGGLE_STATE_DATASET` to `owner/private-dataset-slug` and `RESTORE_BACKUP` to the actual input file path. Keep that dataset updated with the latest backup. This is a manual checkpoint workflow, not automatic cloud synchronization of tokens/videos.

Backups contain metadata, not the source videos or rendered clips. Restoring account settings does not restore media previews. Interrupted uploads/edits may need a fresh job. Downloaded video outputs must be kept separately. OAuth grants can expire or be revoked independently of the runtime.

## Hardware and AI choices

- PeakCut source is pinned to commit `39c32a878648619e981b57af608ba4571a82247f`.
- CPU Parakeet is the fallback. The notebook tries the exact CUDA sherpa-onnx build in the upstream GPU Dockerfile and performs a real model decode probe before accepting it.
- On two GPUs, speech recognition is assigned GPU 0 and Ollama GPU 1. Not every FFmpeg stage is GPU accelerated. Two T4s do not automatically double total speed.
- Local selection uses `qwen2.5:3b`; model quality and source content affect the results. No guaranteed virality or professional unattended-editing claim.
- Current upstream speech model choices are English and Arabic. Hindi/Hinglish and other languages need a separate multilingual transcription adaptation.
- YouTube cloud-IP bot verification is not solved by this package. Start with an uploaded file if a URL is blocked.

## Validation performed

Local checks cover the Worker login/CSRF boundary, authorized heartbeats, tunnel-host validation, saved history, duplicate-start prevention, proxy cookie handling, actual upstream owner login/closed signup, metadata redaction, encrypted backup round-trip and wrong-password rejection. The notebook code cells are syntax checked. The responsive dashboard was opened in a browser with an offline preview backend.

Not yet verified: a real Kaggle T4 installation/render, deployed Cloudflare-to-Kaggle connectivity, Kaggle Secrets behavior for your API-submitted notebook, GitHub dispatch using your token, social OAuth and actual publishing. Those require your account configuration. Do the short uploaded-video smoke test first.

## Troubleshooting

| Symptom | Check |
|---|---|
| Dashboard asks for a password | Use Cloudflare `ADMIN_PASSWORD`, not the Kaggle token |
| Create says sign in first | Open `/app` and sign in with the PeakCut owner email/password |
| Start button disabled | Add Cloudflare `GITHUB_TOKEN`, set `GITHUB_REPO`, deploy again |
| Start requested but no worker | Check Actions submission, then Kaggle notebook output and Secrets |
| Heartbeat fails | Worker origin and bridge token must match; verify D1 schema exists |
| CUDA probe fails | Notebook retries CPU speech; check the diagnostic cell for the actual error |
| No dashboard link | Setup or model startup has not completed; read cell output |
| Worker becomes offline | Last heartbeat is more than 90 seconds old; inspect Kaggle runtime |
| Old project no longer previews | Its media lived in an earlier Kaggle runtime; use saved exported files |
| YouTube confirms you are not a bot | Cloud-source access problem; a different UI does not fix it |

## Upstream references

- PeakCut: https://github.com/haziqahmedqasmi/PeakCut
- PeakCut deployment/account setup: https://github.com/haziqahmedqasmi/PeakCut/blob/main/DEPLOY.md
- Kaggle CLI kernel runs: https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md
- Kaggle notebook specifications: https://www.kaggle.com/docs/notebooks
- Cloudflare Workers: https://developers.cloudflare.com/workers/
- Cloudflare D1: https://developers.cloudflare.com/d1/

PeakCut is MIT licensed; see its upstream LICENSE. The notebook downloads that pinned source with its license intact. No hosted SupoClip code or paid APIs are required.
