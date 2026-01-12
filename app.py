from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mysqldb import MySQL
from passlib.hash import pbkdf2_sha256
import MySQLdb.cursors
import re
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

app.config["MYSQL_HOST"] = config.MYSQL_HOST
app.config["MYSQL_USER"] = config.MYSQL_USER
app.config["MYSQL_PASSWORD"] = config.MYSQL_PASSWORD
app.config["MYSQL_DB"] = config.MYSQL_DB

mysql = MySQL(app)


def is_logged_in():
    return "loggedin" in session


def login_required(role=None):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            if not is_logged_in():
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("Unauthorized", "danger")
                return redirect(url_for("index"))
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator


@app.route("/")
def index():
    return render_template("index.html")


# ---------------- AUTH ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    msg = ""
    if request.method == "POST":
        # field names must match your register.html form
        name = request.form.get("full_name") or request.form.get("name")
        email = request.form.get("email")
        phone = request.form.get("phone")
        password = request.form.get("password")
        confirm = request.form.get("confirm_password")

        # basic validation
        if not name or not email or not password or not confirm:
            msg = "Please fill out all required fields."
            return render_template("register.html", msg=msg)

        if password != confirm:
            msg = "Passwords do not match."
            return render_template("register.html", msg=msg)

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            msg = "Invalid email address."
            return render_template("register.html", msg=msg)

        try:
            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

            # check if email already exists
            cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
            account = cursor.fetchone()
            if account:
                msg = "Account already exists with this email."
                return render_template("register.html", msg=msg)

            # hash password and insert; adjust column names if your table differs
            password_hash = pbkdf2_sha256.hash(password)
            cursor.execute(
                """
                INSERT INTO users (name, email, phone, password_hash, role)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (name, email, phone, password_hash, "donor"),
            )
            mysql.connection.commit()
            flash("Registered successfully. Please log in.", "success")
            return redirect(url_for("login"))

        except Exception:
            msg = "Error creating account. Please try again later."

    return render_template("register.html", msg=msg)


@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Login:
    - Tries real DB users table first.
    - Keeps fallback demo user if DB unreachable.
    """
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        try:
            cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
            cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
            user = cursor.fetchone()
        except Exception:
            user = None

        # real DB login
        if user and pbkdf2_sha256.verify(password, user["password_hash"]):
            session["loggedin"] = True
            session["user_id"] = user["user_id"]
            session["name"] = user["name"]
            session["role"] = user.get("role", "donor")

            try:
                cursor.execute(
                    "SELECT notif_id, message FROM notifications WHERE user_id=%s",
                    (user["user_id"],),
                )
                notifs = cursor.fetchall()
                for n in notifs:
                    flash(f"Notification: {n['message']}", "info")
                mysql.connection.commit()
            except Exception:
                pass

            flash("Logged in successfully.", "success")
            return redirect(url_for("index"))

        # fallback demo login (optional – you can remove this block)
        if email == "demo@example.com" and password == "demo123":
            session["loggedin"] = True
            session["user_id"] = 1
            session["name"] = "Demo User"
            session["role"] = "donor"
            flash("Demo login successful (no database).", "success")
            return redirect(url_for("index"))

        flash("Incorrect email/password.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("login"))


# ---------------- DONOR ----------------

@app.route("/donor/register", methods=["GET", "POST"])
@login_required(role="donor")
def donor_register():
    flash("Donor profile editing is disabled in the online demo.", "info")
    return render_template("donor_register.html")


@app.route("/donor/deactivate", methods=["POST"])
@login_required(role="donor")
def donor_deactivate():
    flash("Deactivation is disabled in the online demo.", "info")
    return redirect(url_for("index"))


@app.route("/donor/delete", methods=["POST"])
@login_required(role="donor")
def donor_delete_self():
    flash("Account deletion is disabled in the online demo.", "info")
    return redirect(url_for("index"))


@app.route("/donors")
@login_required()
def donors_list():
    donors = []
    organ = request.args.get("organ")
    location = request.args.get("location")

    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        query = """SELECT d.*, u.name, u.email, u.phone
                   FROM donors d JOIN users u ON d.user_id = u.user_id
                   WHERE d.availability_status='Active'"""
        params = []
        if organ:
            query += " AND FIND_IN_SET(%s, d.organs)"
            params.append(organ)
        if location:
            query += " AND d.location LIKE %s"
            params.append("%" + location + "%")

        cursor.execute(query, tuple(params))
        donors = cursor.fetchall()
    except Exception:
        flash("Database unavailable; showing empty donor list.", "info")

    return render_template("donors_list.html", donors=donors, organ=organ, location=location)


# ---------------- HOSPITAL REQUESTS ----------------

@app.route("/request/new", methods=["GET", "POST"])
@login_required(role="hospital")
def request_new():
    flash("Creating new requests is disabled in the online demo.", "info")
    return render_template("request_form.html")


@app.route("/request/<int:request_id>/delete", methods=["POST"])
@login_required(role="hospital")
def request_delete(request_id):
    flash("Deleting requests is disabled in the online demo.", "info")
    return redirect(url_for("matches_list"))


# ---------------- MATCHING ENGINE & MATCHES ----------------

def compute_match_score(req, donor, req_location=None):
    score = 0.0

    if req["blood_type"] == donor["blood_type"]:
        score += 50
    elif donor["blood_type"] in ["O-", "O+"]:
        score += 30

    req_org = req["required_organ"]
    if req_org in donor["organs"].split(","):
        score += 30

    if req["hla_profile"] and donor["hla_profile"]:
        if req["hla_profile"] == donor["hla_profile"]:
            score += 15

    if req_location and donor["location"] and req_location.lower() in donor["location"].lower():
        score += 10

    if req["urgency_level"] == "Critical":
        score += 20
    elif req["urgency_level"] == "High":
        score += 10

    return min(score, 100.0)


def create_matches_for_request(request_id, req_location=None):
    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM requests WHERE request_id=%s", (request_id,))
        req = cursor.fetchone()
        if not req:
            return

        cursor.execute(
            """SELECT d.*, u.email, u.user_id
               FROM donors d JOIN users u ON d.user_id = u.user_id
               WHERE d.availability_status='Active'"""
        )
        donors = cursor.fetchall()

        for donor in donors:
            score = compute_match_score(req, donor, req_location)
            if score >= 40:
                cursor.execute(
                    "INSERT INTO matches (request_id, donor_id, score, status) "
                    "VALUES (%s,%s,%s,'Proposed')",
                    (request_id, donor["donor_id"], score),
                )
                match_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO notifications (user_id, match_id, type, message) "
                    "VALUES (%s,%s,%s,%s)",
                    (
                        donor["user_id"],
                        match_id,
                        "MatchFound",
                        f"Potential match for organ request {request_id} with score {score}",
                    ),
                )

        mysql.connection.commit()
    except Exception:
        pass


@app.route("/matches")
@login_required()
def matches_list():
    matches = []
    notifs = []
    unread = 0

    try:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

        if session["role"] == "hospital":
            cursor.execute(
                """SELECT m.*, r.patient_name, r.required_organ, d.blood_type, u.name AS donor_name
                   FROM matches m
                   JOIN requests r ON m.request_id = r.request_id
                   JOIN donors d ON m.donor_id = d.donor_id
                   JOIN users u ON d.user_id = u.user_id
                   ORDER BY m.score DESC"""
            )
        else:
            cursor.execute(
                """SELECT m.*, r.patient_name, r.required_organ, d.blood_type
                   FROM matches m
                   JOIN donors d ON m.donor_id = d.donor_id
                   JOIN users u ON d.user_id = u.user_id
                   JOIN requests r ON m.request_id = r.request_id
                   WHERE u.user_id=%s
                   ORDER BY m.score DESC""",
                (session["user_id"],),
            )
        matches = cursor.fetchall()

        cursor.execute(
            "SELECT * FROM notifications WHERE user_id=%s ORDER BY sent_at DESC",
            (session["user_id"],),
        )
        notifs = cursor.fetchall()

        cursor.execute(
            "SELECT COUNT(*) AS unread_count FROM notifications "
            "WHERE user_id=%s AND status='Unread'",
            (session["user_id"],),
        )
        unread = cursor.fetchone()["unread_count"]
    except Exception:
        flash("Database unavailable; matches and notifications are empty.", "info")

    return render_template(
        "matches.html",
        matches=matches,
        notifications=notifs,
        unread_count=unread,
    )


if __name__ == "__main__":
    app.run(debug=True)
