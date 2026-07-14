# ENG Taha — Daily Dashboard (Python/Flask version)

A small Flask + SQLite app: tasks, a time log, goals/KPIs, and daily
notes — with a real backend (data lives in a database on the server,
not in the browser).

## Step 1 — Create a GitHub account

1. Go to [github.com](https://github.com) and sign up (free).
2. Once signed in, click the **+** in the top right → **New repository**.
3. Name it something like `eng-taha-app`, leave it **Public** or **Private**
   (either works for this), don't add a README/gitignore (you already have
   one), then click **Create repository**.
4. GitHub will show you commands to push an existing folder. From inside
   this project folder, run:

   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/eng-taha-app.git
   git push -u origin main
   ```

   (Replace `YOUR-USERNAME` with your actual GitHub username. The first
   push will ask you to sign in — GitHub will walk you through it.)

## Step 2 — Run it locally (optional, to try it first)

```bash
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:5000**. A `data.db` SQLite file is created
automatically the first time you run it.

## Step 3 — Deploy on Render.com

1. Go to [render.com](https://render.com) and sign up (you can use your
   new GitHub account to sign in — one less password to manage).
2. Click **New → Web Service**, then **connect your GitHub account** and
   select the `eng-taha-app` repo.
3. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
4. Under **Environment**, add these variables:
   - `APP_PASSWORD` → the password you want to sign in with
   - `SECRET_KEY` → any random string (used to sign the login session)
5. Pick an instance type — **Free** is fine to start.
6. Deploy. Render will give you a public URL like
   `https://eng-taha-app.onrender.com`.

## Persistent storage (optional, keeps data across restarts)

Render's **Free** tier doesn't support attaching a disk — the database
can get wiped on redeploys or long sleep periods. If you want your data
to reliably survive:

1. Upgrade the service to the **Starter** plan ($7/month) — this unlocks
   the **Disks** option in service settings.
2. Add a disk: **Mount Path** `/var/data`, **Size** 1 GB.
3. Add one more environment variable: `DB_PATH` → `/var/data/data.db`.

The app already reads `DB_PATH` from the environment (defaulting to a
local file if it's not set) and creates the folder automatically — so
once the disk is attached, tasks/goals/notes survive restarts and
redeploys. Railway and Fly.io work the same way with "volumes" instead
of "disks."

## What's included

Tasks (with priority, due dates, categories, recurring/daily repeat, and
document-link attachments), a time log (manual entries plus a live
start/stop timer, with per-category totals), goals with +/− progress,
daily notes, a history/trend view of the last 14 days, PDF export of any
day's summary, and full backup/restore as JSON.

Not included in this version: subtasks/checklists, search/filter, and
plain-text export. Say the word if you want any of those added too.

## Project structure

```
app.py                 Flask app + all API routes
templates/index.html   The dashboard UI (calls the API via fetch)
templates/login.html   Password gate
requirements.txt
Procfile                for Render/Railway-style deploys
```
