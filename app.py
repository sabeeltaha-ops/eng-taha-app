import os
import sqlite3
import uuid
from datetime import date
from functools import wraps

from flask import Flask, request, jsonify, render_template, session, redirect, url_for, g

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")  # set this on your hosting platform

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            text TEXT NOT NULL,
            pri TEXT NOT NULL DEFAULT 'med',
            done INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS time_entries (
            id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            label TEXT NOT NULL,
            mins INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            target INTEGER NOT NULL,
            current INTEGER NOT NULL DEFAULT 0,
            unit TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS notes (
            date TEXT PRIMARY KEY,
            content TEXT NOT NULL DEFAULT ''
        );
        """
    )
    db.commit()
    db.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if APP_PASSWORD and not session.get("authed"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def api_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if APP_PASSWORD and not session.get("authed"):
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PASSWORD:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["authed"] = True
            return redirect(url_for("index"))
        error = "Wrong password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("authed", None)
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/api/day")
@api_login_required
def get_day():
    d = request.args.get("date", date.today().isoformat())
    db = get_db()
    tasks = [dict(r) for r in db.execute(
        "SELECT * FROM tasks WHERE date=? ORDER BY rowid", (d,)
    )]
    entries = [dict(r) for r in db.execute(
        "SELECT * FROM time_entries WHERE date=? ORDER BY rowid", (d,)
    )]
    note_row = db.execute("SELECT content FROM notes WHERE date=?", (d,)).fetchone()
    for t in tasks:
        t["done"] = bool(t["done"])
    return jsonify({
        "date": d,
        "tasks": tasks,
        "time_entries": entries,
        "notes": note_row["content"] if note_row else ""
    })


@app.route("/api/tasks", methods=["POST"])
@api_login_required
def create_task():
    body = request.get_json(force=True) or {}
    d = body.get("date", date.today().isoformat())
    text = (body.get("text") or "").strip()
    pri = body.get("pri", "med")
    if not text:
        return jsonify({"error": "text is required"}), 400
    if pri not in ("high", "med", "low"):
        pri = "med"
    tid = uuid.uuid4().hex[:9]
    db = get_db()
    db.execute(
        "INSERT INTO tasks (id, date, text, pri, done) VALUES (?,?,?,?,0)",
        (tid, d, text, pri),
    )
    db.commit()
    return jsonify({"id": tid, "date": d, "text": text, "pri": pri, "done": False}), 201


@app.route("/api/tasks/<task_id>", methods=["PATCH"])
@api_login_required
def update_task(task_id):
    body = request.get_json(force=True) or {}
    db = get_db()
    if "done" in body:
        db.execute("UPDATE tasks SET done=? WHERE id=?", (1 if body["done"] else 0, task_id))
    if "text" in body:
        db.execute("UPDATE tasks SET text=? WHERE id=?", (body["text"], task_id))
    if "pri" in body and body["pri"] in ("high", "med", "low"):
        db.execute("UPDATE tasks SET pri=? WHERE id=?", (body["pri"], task_id))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
@api_login_required
def delete_task(task_id):
    db = get_db()
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/time", methods=["POST"])
@api_login_required
def create_time_entry():
    body = request.get_json(force=True) or {}
    d = body.get("date", date.today().isoformat())
    label = (body.get("label") or "").strip()
    try:
        mins = int(body.get("mins", 0))
    except (TypeError, ValueError):
        mins = 0
    if not label or mins <= 0:
        return jsonify({"error": "label and a positive number of minutes are required"}), 400
    eid = uuid.uuid4().hex[:9]
    db = get_db()
    db.execute(
        "INSERT INTO time_entries (id, date, label, mins) VALUES (?,?,?,?)",
        (eid, d, label, mins),
    )
    db.commit()
    return jsonify({"id": eid, "date": d, "label": label, "mins": mins}), 201


@app.route("/api/time/<entry_id>", methods=["DELETE"])
@api_login_required
def delete_time_entry(entry_id):
    db = get_db()
    db.execute("DELETE FROM time_entries WHERE id=?", (entry_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/goals")
@api_login_required
def list_goals():
    db = get_db()
    goals = [dict(r) for r in db.execute("SELECT * FROM goals ORDER BY rowid")]
    return jsonify(goals)


@app.route("/api/goals", methods=["POST"])
@api_login_required
def create_goal():
    body = request.get_json(force=True) or {}
    name = (body.get("name") or "").strip()
    try:
        target = int(body.get("target", 0))
    except (TypeError, ValueError):
        target = 0
    unit = body.get("unit", "") or ""
    if not name or target <= 0:
        return jsonify({"error": "name and a positive target are required"}), 400
    gid = uuid.uuid4().hex[:9]
    db = get_db()
    db.execute(
        "INSERT INTO goals (id, name, target, current, unit) VALUES (?,?,?,0,?)",
        (gid, name, target, unit),
    )
    db.commit()
    return jsonify({"id": gid, "name": name, "target": target, "current": 0, "unit": unit}), 201


@app.route("/api/goals/<goal_id>", methods=["PATCH"])
@api_login_required
def update_goal(goal_id):
    body = request.get_json(force=True) or {}
    db = get_db()
    if "delta" in body:
        row = db.execute("SELECT current FROM goals WHERE id=?", (goal_id,)).fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        new_val = max(0, row["current"] + int(body["delta"]))
        db.execute("UPDATE goals SET current=? WHERE id=?", (new_val, goal_id))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/goals/<goal_id>", methods=["DELETE"])
@api_login_required
def delete_goal(goal_id):
    db = get_db()
    db.execute("DELETE FROM goals WHERE id=?", (goal_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/notes", methods=["PUT"])
@api_login_required
def save_notes():
    body = request.get_json(force=True) or {}
    d = body.get("date", date.today().isoformat())
    content = body.get("content", "")
    db = get_db()
    db.execute(
        "INSERT INTO notes (date, content) VALUES (?, ?) "
        "ON CONFLICT(date) DO UPDATE SET content=excluded.content",
        (d, content),
    )
    db.commit()
    return jsonify({"ok": True})


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
