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
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        phone = request.form.get("phone")
        password = request.form.get("password")
        role = request.form.get("role")  # donor/hospital
        consent = 1 if request.form.get("consent") == "on" else 0

        if not name or not email or not password or role not in ["donor", "hospital"]:
            flash("Please fill all required fields.", "danger")
            return render_template("register.html")

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash("Invalid email.", "danger")
            return render_template("register.html")

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        account = cursor.fetchone()
        if account:
            flash("Account with this email already exists.", "danger")
            return render_template("register.html")

        password_hash = pbkdf2_sha256.hash(password)

        cursor.execute(
            "INSERT INTO users (name, email, phone, password_hash, role, consent_given) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (name, email, phone, password_hash, role, consent),
        )
        mysql.connection.commit()
        user_id = cursor.lastrowid

        if role == "hospital":
            cursor.execute(
                "INSERT INTO hospitals (name, address, contact_email, contact_phone, admin_user_id) "
                "VALUES (%s,%s,%s,%s,%s)",
                (name + " Hospital", "", email, phone, user_id),
            )
            mysql.connection.commit()

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()

        if user and pbkdf2_sha256.verify(password, user["password_hash"]):
            session["loggedin"] = True
            session["user_id"] = user["user_id"]
            session["name"] = user["name"]
            session["role"] = user["role"]

            # POP ALL NOTIFICATIONS ON EVERY LOGIN (Read or Unread)
            cursor.execute(
                "SELECT notif_id, message FROM notifications "
                "WHERE user_id=%s",
                (user["user_id"],),
            )
            notifs = cursor.fetchall()
            for n in notifs:
                flash(f"Notification: {n['message']}", "info")
            mysql.connection.commit()

            flash("Logged in successfully.", "success")
            return redirect(url_for("index"))
        else:
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
    if request.method == "POST":
        blood_type = request.form.get("blood_type")
        organs = ",".join(request.form.getlist("organs"))
        hla_profile = request.form.get("hla_profile")
        availability_status = request.form.get("availability_status")
        location = request.form.get("location")

        if not blood_type or not organs:
            flash("Blood type and at least one organ are required.", "danger")
            return render_template("donor_register.html")

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM donors WHERE user_id=%s", (session["user_id"],))
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                """UPDATE donors SET blood_type=%s, organs=%s, hla_profile=%s,
                   availability_status=%s, location=%s WHERE user_id=%s""",
                (blood_type, organs, hla_profile, availability_status, location, session["user_id"]),
            )
        else:
            cursor.execute(
                """INSERT INTO donors (user_id, blood_type, organs, hla_profile,
                   availability_status, location)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (session["user_id"], blood_type, organs, hla_profile, availability_status, location),
            )
        mysql.connection.commit()
        flash("Donor profile saved.", "success")
        return redirect(url_for("index"))

    return render_template("donor_register.html")


@app.route("/donor/deactivate", methods=["POST"])
@login_required(role="donor")
def donor_deactivate():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # set donor inactive
    cursor.execute(
        "UPDATE donors SET availability_status='Inactive' WHERE user_id=%s",
        (session["user_id"],),
    )

    # mark notifications as Read when donor is deactivated
    cursor.execute(
        "UPDATE notifications SET status='Read' "
        "WHERE user_id=%s AND status='Unread'",
        (session["user_id"],),
    )

    mysql.connection.commit()
    flash("Your donor profile is now Inactive. Notifications cleared.", "success")
    return redirect(url_for("index"))


@app.route("/donor/delete", methods=["POST"])
@login_required(role="donor")
def donor_delete_self():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("DELETE FROM users WHERE user_id=%s", (session["user_id"],))
    mysql.connection.commit()
    session.clear()
    flash("Your donor account has been deleted.", "success")
    return redirect(url_for("index"))


@app.route("/donors")
@login_required()
def donors_list():
    organ = request.args.get("organ")
    location = request.args.get("location")

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
    return render_template("donors_list.html", donors=donors, organ=organ, location=location)


# ---------------- HOSPITAL REQUESTS ----------------

@app.route("/request/new", methods=["GET", "POST"])
@login_required(role="hospital")
def request_new():
    if request.method == "POST":
        patient_name = request.form.get("patient_name")
        required_organ = request.form.get("required_organ")
        blood_type = request.form.get("blood_type")
        hla_profile = request.form.get("hla_profile")
        urgency_level = request.form.get("urgency_level")
        location = request.form.get("location")

        if not patient_name or not required_organ or not blood_type or not urgency_level:
            flash("Please fill all required fields.", "danger")
            return render_template("request_form.html")

        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT hospital_id FROM hospitals WHERE admin_user_id=%s", (session["user_id"],))
        hospital = cursor.fetchone()
        if not hospital:
            flash("Hospital record not found.", "danger")
            return render_template("request_form.html")

        cursor.execute(
            """INSERT INTO requests (hospital_id, patient_name, required_organ,
               blood_type, hla_profile, urgency_level, status)
               VALUES (%s,%s,%s,%s,%s,%s,'Pending')""",
            (hospital["hospital_id"], patient_name, required_organ, blood_type, hla_profile, urgency_level),
        )
        mysql.connection.commit()
        request_id = cursor.lastrowid

        create_matches_for_request(request_id, location)
        flash("Request submitted and matching started.", "success")
        return redirect(url_for("matches_list"))

    return render_template("request_form.html")


# NEW: delete request after transplant
@app.route("/request/<int:request_id>/delete", methods=["POST"])
@login_required(role="hospital")
def request_delete(request_id):
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # ensure this request belongs to current hospital user
    cursor.execute(
        """SELECT r.request_id
           FROM requests r
           JOIN hospitals h ON r.hospital_id = h.hospital_id
           WHERE r.request_id = %s AND h.admin_user_id = %s""",
        (request_id, session["user_id"]),
    )
    req = cursor.fetchone()
    if not req:
        flash("Request not found or you are not allowed to delete it.", "danger")
        return redirect(url_for("matches_list"))

    # delete matches linked to this request
    cursor.execute("DELETE FROM matches WHERE request_id = %s", (request_id,))

    # delete the request itself
    cursor.execute("DELETE FROM requests WHERE request_id = %s", (request_id,))

    mysql.connection.commit()
    flash(f"Request {request_id} deleted after successful transplant.", "success")
    return redirect(url_for("matches_list"))


# ---------------- MATCHING ENGINE ----------------

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
                (donor["user_id"], match_id, "MatchFound",
                 f"Potential match for organ request {request_id} with score {score}"),
            )

    mysql.connection.commit()


# ---------------- MATCHES & NOTIFICATIONS ----------------

@app.route("/matches")
@login_required()
def matches_list():
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

    return render_template(
        "matches.html",
        matches=matches,
        notifications=notifs,
        unread_count=unread,
    )


if __name__ == "__main__":
    app.run(debug=True)
