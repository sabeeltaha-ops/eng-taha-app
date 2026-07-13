# ENG Taha — Daily Dashboard (Python/Flask version)

A small Flask + SQLite app: tasks (with priority), a time log, goals/KPIs,
and daily notes. This is the "real backend" version — data lives in a
database on the server, not in the browser.

## Run it locally

```bash
pip install -r requirements.txt
python app.py
```

Then open **http://localhost:5000**. A `data.db` SQLite file is created
automatically the first time you run it.

By default there's no password. To protect it, set `APP_PASSWORD` before
starting:

```bash
APP_PASSWORD="pick-something" python app.py
```

## Deploying it publicly (Render.com — free tier)

1. Push this folder to a GitHub repo (or use Render's "deploy from a
   folder" option if offered).
2. On [render.com](https://render.com), click **New → Web Service**,
   connect the repo.
3. Settings:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
4. Under **Environment**, add:
   - `APP_PASSWORD` → the password you want to use to sign in
   - `SECRET_KEY` → any random string (used to sign the login session)
5. Deploy. Render gives you a public URL like
   `https://eng-taha.onrender.com`.

Railway and Fly.io work the same way — same `Procfile`
(`web: gunicorn app:app`) and the same two environment variables.

## Important: SQLite is not durable on most free hosting

Free-tier web services on Render, Railway, etc. usually run on an
**ephemeral filesystem** — the `data.db` file can be wiped whenever the
app restarts, sleeps, or redeploys. This is fine for trying it out, but
for anything you actually rely on day to day, do one of:

- **Add a persistent disk/volume** to the service (Render and Railway
  both offer this, sometimes on a paid plan) and point `DB_PATH` at a
  file inside it, or
- **Swap SQLite for a hosted Postgres database** (free options: Neon,
  Supabase, Railway's Postgres add-on). This is a bigger change to
  `app.py` (swap `sqlite3` calls for a Postgres driver) — say the word
  if you want this version instead.

## What's different from the browser version

To keep this rewrite focused, it's the core feature set only:
tasks (with priority), a time log, goals with +/− progress, and a daily
notes field. The extras from the browser version (subtasks, due dates,
categories, recurring tasks, the live timer, history/trend view,
attachments, and TXT/PDF/backup export) aren't in this version — happy
to add any of them back into the Flask app if you want them here too.

## Project structure

```
app.py                 Flask app + all API routes
templates/index.html   The dashboard UI (calls the API via fetch)
templates/login.html   Password gate
requirements.txt
Procfile                for Render/Railway-style deploys
```
