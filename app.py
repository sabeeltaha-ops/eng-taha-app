import io
import json
import os
import sqlite3
import textwrap
import uuid
from datetime import date, timedelta
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template, session, redirect,
    url_for, g, send_file
)
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.lib.pagesizes import letter

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")  # set this on your hosting platform

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "data.db"))
os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)


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


def _ensure_column(db, table, col, coltype):
    cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")


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
        CREATE TABLE IF NOT EXISTS recurring (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            pri TEXT NOT NULL DEFAULT 'med',
            category TEXT
        );
        """
    )
    # Migrate older deployed DBs that predate these columns
    _ensure_column(db, "tasks", "due", "TEXT")
    _ensure_column(db, "tasks", "category", "TEXT")
    _ensure_column(db, "tasks", "link", "TEXT")
    _ensure_column(db, "tasks", "recurring_id", "TEXT")
    _ensure_column(db, "time_entries", "category", "TEXT")
    db.commit()
    db.close()


def apply_recurring_tasks(db, d):
    """Instantiate today's copy of any recurring task template that isn't
    already present for the given date. Only runs for today's date."""
    if d != date.today().isoformat():
        return
    templates = db.execute("SELECT * FROM recurring").fetchall()
    for tmpl in templates:
        exists = db.execute(
            "SELECT 1 FROM tasks WHERE date=? AND recurring_id=?", (d, tmpl["id"])
        ).fetchone()
        if not exists:
            tid = uuid.uuid4().hex[:9]
            db.execute(
                "INSERT INTO tasks (id, date, text, pri, done, category, recurring_id) "
                "VALUES (?,?,?,?,0,?,?)",
                (tid, d, tmpl["text"], tmpl["pri"], tmpl["category"], tmpl["id"]),
            )
    db.commit()


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


# ---------- Day (tasks + time entries + notes) ----------

@app.route("/api/day")
@api_login_required
def get_day():
    d = request.args.get("date", date.today().isoformat())
    db = get_db()
    apply_recurring_tasks(db, d)
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


# ---------- Tasks ----------

@app.route("/api/tasks", methods=["POST"])
@api_login_required
def create_task():
    body = request.get_json(force=True) or {}
    d = body.get("date", date.today().isoformat())
    text = (body.get("text") or "").strip()
    pri = body.get("pri", "med")
    due = body.get("due") or None
    category = (body.get("category") or "").strip() or None
    make_recurring = bool(body.get("recurring"))

    if not text:
        return jsonify({"error": "text is required"}), 400
    if pri not in ("high", "med", "low"):
        pri = "med"

    db = get_db()
    recurring_id = None
    if make_recurring:
        recurring_id = uuid.uuid4().hex[:9]
        db.execute(
            "INSERT INTO recurring (id, text, pri, category) VALUES (?,?,?,?)",
            (recurring_id, text, pri, category),
        )
    tid = uuid.uuid4().hex[:9]
    db.execute(
        "INSERT INTO tasks (id, date, text, pri, done, due, category, recurring_id) "
        "VALUES (?,?,?,?,0,?,?,?)",
        (tid, d, text, pri, due, category, recurring_id),
    )
    db.commit()
    return jsonify({
        "id": tid, "date": d, "text": text, "pri": pri, "done": False,
        "due": due, "category": category, "link": None, "recurring_id": recurring_id
    }), 201


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
    if "due" in body:
        db.execute("UPDATE tasks SET due=? WHERE id=?", (body["due"] or None, task_id))
    if "category" in body:
        db.execute("UPDATE tasks SET category=? WHERE id=?", (body["category"] or None, task_id))
    if "link" in body:
        db.execute("UPDATE tasks SET link=? WHERE id=?", (body["link"] or None, task_id))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
@api_login_required
def delete_task(task_id):
    stop_recurring = request.args.get("stop_recurring") == "1"
    db = get_db()
    row = db.execute("SELECT recurring_id FROM tasks WHERE id=?", (task_id,)).fetchone()
    db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    if stop_recurring and row and row["recurring_id"]:
        db.execute("DELETE FROM recurring WHERE id=?", (row["recurring_id"],))
    db.commit()
    return jsonify({"ok": True})


# ---------- Time log ----------

@app.route("/api/time", methods=["POST"])
@api_login_required
def create_time_entry():
    body = request.get_json(force=True) or {}
    d = body.get("date", date.today().isoformat())
    label = (body.get("label") or "").strip()
    category = (body.get("category") or "").strip() or None
    try:
        mins = int(body.get("mins", 0))
    except (TypeError, ValueError):
        mins = 0
    if not label or mins <= 0:
        return jsonify({"error": "label and a positive number of minutes are required"}), 400
    eid = uuid.uuid4().hex[:9]
    db = get_db()
    db.execute(
        "INSERT INTO time_entries (id, date, label, mins, category) VALUES (?,?,?,?,?)",
        (eid, d, label, mins, category),
    )
    db.commit()
    return jsonify({"id": eid, "date": d, "label": label, "mins": mins, "category": category}), 201


# ---------- Categories (for autocomplete) ----------

@app.route("/api/categories")
@api_login_required
def list_categories():
    db = get_db()
    cats = set()
    for row in db.execute("SELECT DISTINCT category FROM tasks WHERE category IS NOT NULL"):
        cats.add(row["category"])
    for row in db.execute("SELECT DISTINCT category FROM time_entries WHERE category IS NOT NULL"):
        cats.add(row["category"])
    for row in db.execute("SELECT DISTINCT category FROM recurring WHERE category IS NOT NULL"):
        cats.add(row["category"])
    return jsonify(sorted(c for c in cats if c))


# ---------- Goals ----------

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


# ---------- Notes ----------

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


# ---------- History / trend ----------

@app.route("/api/history")
@api_login_required
def get_history():
    try:
        days = int(request.args.get("days", 14))
    except (TypeError, ValueError):
        days = 14
    days = max(1, min(days, 60))
    db = get_db()
    today = date.today()
    result = []
    for i in range(days):
        d = (today - timedelta(days=i)).isoformat()
        total = db.execute("SELECT COUNT(*) c FROM tasks WHERE date=?", (d,)).fetchone()["c"]
        done_count = db.execute(
            "SELECT COUNT(*) c FROM tasks WHERE date=? AND done=1", (d,)
        ).fetchone()["c"]
        mins = db.execute(
            "SELECT COALESCE(SUM(mins),0) m FROM time_entries WHERE date=?", (d,)
        ).fetchone()["m"]
        result.append({"date": d, "done": done_count, "total": total, "mins": mins})
    return jsonify(result)


# ---------- PDF export ----------

def _wrap_notes(text, width=88):
    lines = []
    for para in (text.splitlines() or [""]):
        wrapped = textwrap.wrap(para, width) or [""]
        lines.extend(wrapped)
    return lines


@app.route("/api/export.pdf")
@api_login_required
def export_pdf():
    d = request.args.get("date", date.today().isoformat())
    db = get_db()
    tasks = db.execute("SELECT * FROM tasks WHERE date=? ORDER BY rowid", (d,)).fetchall()
    entries = db.execute("SELECT * FROM time_entries WHERE date=? ORDER BY rowid", (d,)).fetchall()
    goals = db.execute("SELECT * FROM goals ORDER BY rowid").fetchall()
    note_row = db.execute("SELECT content FROM notes WHERE date=?", (d,)).fetchone()
    notes = note_row["content"] if note_row else ""

    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    width, height = letter
    left = 50
    state = {"y": height - 50}

    def line(text, size=10, bold=False, gap=16):
        if state["y"] < 50:
            c.showPage()
            state["y"] = height - 50
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(left, state["y"], text)
        state["y"] -= gap

    line(f"ENG TAHA — DAILY SUMMARY — {d}", size=14, bold=True, gap=26)

    line("TASKS", size=12, bold=True, gap=18)
    if not tasks:
        line("  (none)")
    for t in tasks:
        mark = "x" if t["done"] else " "
        extra = ""
        if t["category"]:
            extra += f" ({t['category']})"
        if t["due"]:
            extra += f" — due {t['due']}"
        line(f"  [{mark}] {t['text']}{extra}")
    state["y"] -= 6

    line("TIME LOG", size=12, bold=True, gap=18)
    if not entries:
        line("  (none)")
    for e in entries:
        cat = f" [{e['category']}]" if e["category"] else ""
        line(f"  {e['label']}{cat} — {e['mins']}m")
    total_mins = sum(e["mins"] for e in entries)
    line(f"  Total: {total_mins // 60}h {total_mins % 60}m")
    state["y"] -= 6

    line("GOALS", size=12, bold=True, gap=18)
    if not goals:
        line("  (none)")
    for goal in goals:
        line(f"  {goal['name']}: {goal['current']}/{goal['target']} {goal['unit'] or ''}")
    state["y"] -= 6

    line("NOTES", size=12, bold=True, gap=18)
    if notes.strip():
        for chunk in _wrap_notes(notes):
            line(f"  {chunk}")
    else:
        line("  (none)")

    c.save()
    buf.seek(0)
    return send_file(
        buf, mimetype="application/pdf", as_attachment=True,
        download_name=f"eng-taha-{d}.pdf"
    )


# ---------- Backup / restore ----------

@app.route("/api/backup")
@api_login_required
def backup():
    db = get_db()
    data = {
        "tasks": [dict(r) for r in db.execute("SELECT * FROM tasks")],
        "time_entries": [dict(r) for r in db.execute("SELECT * FROM time_entries")],
        "goals": [dict(r) for r in db.execute("SELECT * FROM goals")],
        "notes": [dict(r) for r in db.execute("SELECT * FROM notes")],
        "recurring": [dict(r) for r in db.execute("SELECT * FROM recurring")],
    }
    buf = io.BytesIO(json.dumps(data, indent=2).encode("utf-8"))
    return send_file(
        buf, mimetype="application/json", as_attachment=True,
        download_name=f"eng-taha-backup-{date.today().isoformat()}.json"
    )


@app.route("/api/restore", methods=["POST"])
@api_login_required
def restore():
    body = request.get_json(force=True) or {}
    db = get_db()
    try:
        db.execute("DELETE FROM tasks")
        db.execute("DELETE FROM time_entries")
        db.execute("DELETE FROM goals")
        db.execute("DELETE FROM notes")
        db.execute("DELETE FROM recurring")

        for t in body.get("tasks", []):
            db.execute(
                "INSERT INTO tasks (id, date, text, pri, done, due, category, link, recurring_id) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (t.get("id"), t.get("date"), t.get("text"), t.get("pri", "med"),
                 1 if t.get("done") else 0, t.get("due"), t.get("category"),
                 t.get("link"), t.get("recurring_id")),
            )
        for e in body.get("time_entries", []):
            db.execute(
                "INSERT INTO time_entries (id, date, label, mins, category) VALUES (?,?,?,?,?)",
                (e.get("id"), e.get("date"), e.get("label"), e.get("mins", 0), e.get("category")),
            )
        for goal in body.get("goals", []):
            db.execute(
                "INSERT INTO goals (id, name, target, current, unit) VALUES (?,?,?,?,?)",
                (goal.get("id"), goal.get("name"), goal.get("target", 0),
                 goal.get("current", 0), goal.get("unit", "")),
            )
        for n in body.get("notes", []):
            db.execute(
                "INSERT INTO notes (date, content) VALUES (?,?)",
                (n.get("date"), n.get("content", "")),
            )
        for r in body.get("recurring", []):
            db.execute(
                "INSERT INTO recurring (id, text, pri, category) VALUES (?,?,?,?)",
                (r.get("id"), r.get("text"), r.get("pri", "med"), r.get("category")),
            )
        db.commit()
    except Exception as exc:
        db.rollback()
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
