from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_bcrypt import Bcrypt
import sqlite3
import requests
import os

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change_this_to_a_random_secret")
bcrypt = Bcrypt(app)

# -------------------------
# ThingSpeak Configuration
# -------------------------
# *** CHANGE THESE TO YOUR CHANNEL / READ API KEY ***
THINGSPEAK_CHANNEL_ID = "3098199"
#THINGSPEAK_CHANNEL_SECRET = ""
THINGSPEAK_READ_API_KEY = "O1MK5ODEM3Z7SKTE"
# Field mapping: field number -> display name (used for routing)
FIELD_MAP = {
    2: "Panel Output (V)",
    3: "Dust Level (Cm)",
    4: "Cleaning Status"
}

# -------------------------
# Database helpers
# -------------------------
DB_PATH = "database.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# -------------------------
# ThingSpeak helper
# -------------------------
def fetch_thingspeak_field(field, results=50):
    """
    Fetch field data from ThingSpeak field endpoint and return a list of dicts:
    [{ 'created_at': ..., 'value': ... }, ...]
    """
    if not THINGSPEAK_CHANNEL_ID:
        return []

    url = f"https://api.thingspeak.com/channels/3098199/fields/{field}.json"
    params = {"THINGSPEAK_READ_API_KEY": THINGSPEAK_READ_API_KEY, "results": 20}
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        feeds = data.get("feeds", [])
        out = []
        # ThingSpeak returns each feed with "fieldN" keys
        key = f"field{field}"
        for feed in feeds:
            raw = feed.get(key)
            if raw is None or raw == "":
                value = None
            else:
                value = raw
            out.append({
                "created_at": feed.get("created_at"),
                "value": value
            })
        return out
    except Exception:
        return []

def fetch_latest_feeds(results=1):

    if not THINGSPEAK_CHANNEL_ID:
        return []
    url = f"https://api.thingspeak.com/channels/3098199/feeds.json"
    params = {"O1MK5ODEM3Z7SKTE": THINGSPEAK_READ_API_KEY, "results": results}
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()
        feeds = data.get("feeds", [])
        return feeds
    except Exception:
        return []

# -------------------------
# Routes: Auth
# -------------------------
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("Provide username and password.", "danger")
            return render_template("signup.html")

        hashed = bcrypt.generate_password_hash(password).decode("utf-8")
        conn = get_db_connection()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed))
            conn.commit()
            flash("Account created successfully. Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already taken. Choose another.", "danger")
        finally:
            conn.close()
    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT id, password FROM users WHERE username = ?", (username,))
        row = c.fetchone()
        conn.close()
        if row and bcrypt.check_password_hash(row["password"], password):
            session["user_id"] = row["id"]
            session["username"] = username
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid credentials.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))

# -------------------------
# Dashboard & API endpoints
# -------------------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    # fetch latest combined feed to display latest values
    latest = fetch_latest_feeds(results=1)
    latest_entry = latest[-1] if latest else None

    # supply a small preview dataset for charts (last 12)
    # The frontend will call /api/field/<n> to get chart data dynamically anyway
    return render_template("dashboard.html", latest=latest_entry, field_map=FIELD_MAP)

@app.route("/details/<int:field>")
def details(field):
    if "user_id" not in session:
        return redirect(url_for("login"))
    if field not in FIELD_MAP:
        flash("Invalid field.", "danger")
        return redirect(url_for("dashboard"))
    # history for server-side rendering fallback (we'll also fetch via AJAX)
    history = fetch_thingspeak_field(field, results=100)
    return render_template("details.html", field=field, title=FIELD_MAP[field], history=history)

# JSON API: return data for a field for Chart.js
@app.route("/api/field/<int:field>")
def api_field(field):
    if "user_id" not in session:
        return jsonify({"error": "unauthorized"}), 401
    results = request.args.get("results", 50, type=int)
    data = fetch_thingspeak_field(field, results=results)
    # Return arrays of labels (timestamps) and values
    labels = [entry["created_at"] for entry in data]
    values = [None if entry["value"] is None else entry["value"] for entry in data]
    return jsonify({"labels": labels, "values": values})

# Quick status check
@app.route("/health")
def health():
    return "OK", 200

if __name__ == "__main__":
    app.run(debug=True)
