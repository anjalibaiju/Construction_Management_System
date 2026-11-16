
from django import db
from django import db
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from pathlib import Path
from datetime import datetime
import sqlite3

# Create Flask application
app = Flask(__name__)
app.secret_key = "construction_system_secret_key"

# Project folders
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)

app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}


# 1. DATABASE CONNECTION
def get_db():
    db = sqlite3.connect(BASE_DIR / "construction.db")
    db.row_factory = sqlite3.Row
    return db


# 2. CREATE DATABASE TABLES
def init_db():
    db = get_db()

    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS enquiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        status TEXT DEFAULT 'Pending',
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        enquiry_id INTEGER,
        client_id INTEGER NOT NULL,
        staff_id INTEGER,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        progress INTEGER DEFAULT 0,
        status TEXT DEFAULT 'Not Started',
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS proofs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        staff_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        note TEXT,
        uploaded_at TEXT,
        
        status TEXT DEFAULT 'Pending'
    );

    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        method TEXT NOT NULL,
        status TEXT DEFAULT 'Submitted',
        created_at TEXT
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT
    );
    """)
        # Add status column to existing proofs table
    proof_columns = db.execute(
        "PRAGMA table_info(proofs)"
    ).fetchall()

    if not any(column["name"] == "status" for column in proof_columns):
        db.execute(
            "ALTER TABLE proofs ADD COLUMN status TEXT DEFAULT 'Pending'"
        )

    # Create default admin account
    admin = db.execute(
        "SELECT id FROM users WHERE email=?",
        ("admin@cms.com",)
    ).fetchone()

    if not admin:
        db.execute(
            """INSERT INTO users
            (name, email, password, role)
            VALUES (?, ?, ?, ?)""",
            (
                "Administrator",
                "admin@cms.com",
                generate_password_hash("admin123"),
                "admin"
            )
        )

    db.commit()
    db.close()


# 3. NOTIFICATION FUNCTION
def notify(user_id, message):
    db = get_db()

    db.execute(
        """INSERT INTO notifications
        (user_id, message, created_at)
        VALUES (?, ?, ?)""",
        (
            user_id,
            message,
            datetime.now().strftime("%d-%m-%Y %H:%M")
        )
    )

    db.commit()
    db.close()


# 4. LOGIN CHECK
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.")
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapper


# 5. ROLE CHECK
def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):

            if "user_id" not in session:
                return redirect(url_for("login"))

            if session.get("role") not in roles:
                flash("Access denied.")
                return redirect(url_for("dashboard"))

            return view(*args, **kwargs)

        return wrapper

    return decorator


# 6. HOME PAGE
@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    return render_template("home.html")


# 7. USER REGISTRATION
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or len(password) < 6:
            flash("Enter all details. Password must have at least 6 characters.")
            return redirect(url_for("register"))

        db = get_db()

        try:
            db.execute(
                """INSERT INTO users
                (name, email, password, role)
                VALUES (?, ?, ?, ?)""",
                (
                    name,
                    email,
                    generate_password_hash(password),
                    "user"
                )
            )

            db.commit()
            flash("Registration successful. Please login.")

            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("Email already registered.")

        finally:
            db.close()

    return render_template("register.html")


# 8. USER LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()

        user = db.execute(
            "SELECT * FROM users WHERE email=?",
            (email,)
        ).fetchone()

        db.close()

        if user and check_password_hash(user["password"], password):

            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]

            return redirect(url_for("dashboard"))

        flash("Invalid email or password.")

    return render_template("login.html")


# 9. LOGOUT
@app.route("/logout")
def logout():

    session.clear()

    flash("Logged out successfully.")

    return redirect(url_for("home"))


# 10. DASHBOARD
@app.route("/dashboard")
@login_required
def dashboard():

    db = get_db()

    role = session["role"]
    user_id = session["user_id"]

    if role == "admin":

        counts = {
            "users": db.execute(
                "SELECT COUNT(*) FROM users WHERE role='user'"
            ).fetchone()[0],

            "staff": db.execute(
                "SELECT COUNT(*) FROM users WHERE role='staff'"
            ).fetchone()[0],

            "enquiries": db.execute(
                "SELECT COUNT(*) FROM enquiries"
            ).fetchone()[0],

            "projects": db.execute(
                "SELECT COUNT(*) FROM projects"
            ).fetchone()[0],

            "payments": db.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status='Approved'"
            ).fetchone()[0]
        }

        projects = db.execute("""
            SELECT p.*, u.name AS client_name,
            s.name AS staff_name
            FROM projects p
            JOIN users u ON p.client_id = u.id
            LEFT JOIN users s ON p.staff_id = s.id
            ORDER BY p.id DESC
        """).fetchall()

        enquiries = db.execute("""
            SELECT e.*, u.name AS client_name
            FROM enquiries e
            JOIN users u ON e.user_id = u.id
            ORDER BY e.id DESC
        """).fetchall()

        staff = db.execute(
            "SELECT id, name, email FROM users WHERE role='staff'"
        ).fetchall()

        proofs = db.execute("""
             SELECT proofs.*,
           projects.title AS project_title,
           users.name AS staff_name
            FROM proofs
    JOIN projects ON proofs.project_id = projects.id
    JOIN users ON proofs.staff_id = users.id
    ORDER BY proofs.id DESC
""").fetchall()

        db.close()

            
        


        

        return render_template(
            "admin_dashboard.html",
            counts=counts,
            projects=projects,
            enquiries=enquiries,
            staff=staff,
            proofs=proofs
        )

    elif role == "staff":

        projects = db.execute("""
            SELECT p.*, u.name AS client_name
            FROM projects p
            JOIN users u ON p.client_id = u.id
            WHERE p.staff_id=?
        """, (user_id,)).fetchall()

    else:

        projects = db.execute(
            "SELECT * FROM projects WHERE client_id=?",
            (user_id,)
        ).fetchall()

    notifications = db.execute(
        """SELECT * FROM notifications
        WHERE user_id=?
        ORDER BY id DESC LIMIT 8""",
        (user_id,)
    ).fetchall()

    db.close()

    return render_template(
        "dashboard.html",
        projects=projects,
        notifications=notifications
    )


# 11. CLIENT ENQUIRY
@app.route("/enquiry", methods=["GET", "POST"])
@login_required
@role_required("user")
def enquiry():

    if request.method == "POST":

        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        if title and description:

            db = get_db()

            db.execute(
                """INSERT INTO enquiries
                (user_id, title, description, status, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    session["user_id"],
                    title,
                    description,
                    "Pending",
                    datetime.now().strftime("%d-%m-%Y")
                )
            )

            db.commit()
            db.close()

            notify(
                1,
                "New construction enquiry: " + title
            )

            flash("Enquiry submitted successfully.")

            return redirect(url_for("dashboard"))

        flash("Please enter all details.")

    return render_template("enquiry.html")


# 12. ADMIN APPROVES OR REJECTS ENQUIRY
@app.route("/admin/enquiry/<int:enquiry_id>/<action>", methods=["POST"])
@login_required
@role_required("admin")
def manage_enquiry(enquiry_id, action):

    if action not in ["approve", "reject"]:
        return redirect(url_for("dashboard"))

    db = get_db()

    enquiry_data = db.execute(
        "SELECT * FROM enquiries WHERE id=?",
        (enquiry_id,)
    ).fetchone()

    if enquiry_data:

        status = "Approved" if action == "approve" else "Rejected"

        db.execute(
            "UPDATE enquiries SET status=? WHERE id=?",
            (status, enquiry_id)
        )

        if action == "approve":

            db.execute(
                """INSERT INTO projects
                (enquiry_id, client_id, title, description, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    enquiry_id,
                    enquiry_data["user_id"],
                    enquiry_data["title"],
                    enquiry_data["description"],
                    datetime.now().strftime("%d-%m-%Y")
                )
            )

        db.commit()

        notify(
            enquiry_data["user_id"],
            "Your enquiry was " + status.lower()
        )

    db.close()

    flash("Enquiry status updated.")

    return redirect(url_for("dashboard"))


# 13. ADD STAFF
@app.route("/admin/add-staff", methods=["POST"])
@login_required
@role_required("admin")
def add_staff():

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not name or not email or len(password) < 6:
        flash("Enter valid staff details and a password of at least 6 characters.")
        return redirect(url_for("dashboard"))

    db = get_db()

    try:
        db.execute(
            """INSERT INTO users
            (name, email, password, role)
            VALUES (?, ?, ?, ?)""",
            (
                name,
                email,
                generate_password_hash(password),
                "staff"
            )
        )

        db.commit()
        flash("Staff account created.")

    except sqlite3.IntegrityError:
        flash("Email already exists.")

    finally:
        db.close()

    return redirect(url_for("dashboard"))


# 14. ASSIGN STAFF TO PROJECT
@app.route("/admin/assign/<int:project_id>", methods=["POST"])
@login_required
@role_required("admin")
def assign_staff(project_id):

    staff_id = request.form.get("staff_id", type=int)

    db = get_db()

    staff = db.execute(
        "SELECT id FROM users WHERE id=? AND role='staff'",
        (staff_id,)
    ).fetchone()

    project = db.execute(
        "SELECT * FROM projects WHERE id=?",
        (project_id,)
    ).fetchone()

    if staff and project:

        db.execute(
            "UPDATE projects SET staff_id=? WHERE id=?",
            (staff_id, project_id)
        )

        db.commit()

        notify(
            staff_id,
            "You have been assigned to project: " + project["title"]
        )

        flash("Staff assigned successfully.")

    else:
        flash("Invalid staff or project.")

    db.close()

    return redirect(url_for("dashboard"))


# 15. UPDATE PROJECT PROGRESS
@app.route("/project/<int:project_id>/progress", methods=["POST"])
@login_required
@role_required("staff")
def update_progress(project_id):

    progress = request.form.get("progress", type=int)

    if progress is None or not 0 <= progress <= 100:
        flash("Enter progress between 0 and 100.")
        return redirect(url_for("dashboard"))

    status = (
        "Completed" if progress == 100
        else "In Progress" if progress > 0
        else "Not Started"
    )

    db = get_db()

    project = db.execute(
        """SELECT * FROM projects
        WHERE id=? AND staff_id=?""",
        (project_id, session["user_id"])
    ).fetchone()

    if project:

        db.execute(
            "UPDATE projects SET progress=?, status=? WHERE id=?",
            (progress, status, project_id)
        )

        db.commit()

        notify(
            project["client_id"],
            f"Project {project['title']} progress is now {progress}%."
        )

        flash("Project progress updated.")

    else:
        flash("Project not assigned to you.")

    db.close()

    return redirect(url_for("dashboard"))


# 16. UPLOAD PROOF OF WORK
@app.route("/project/<int:project_id>/proof", methods=["POST"])
@login_required
@role_required("staff")
def upload_proof(project_id):

    file = request.files.get("proof")
    note = request.form.get("note", "").strip()

    if not file or file.filename == "":
        flash("Please select a file.")
        return redirect(url_for("dashboard"))

    if "." not in file.filename or file.filename.rsplit(".", 1)[1].lower() not in ALLOWED_EXTENSIONS:
        flash("Only JPG, JPEG, PNG and PDF files are allowed.")
        return redirect(url_for("dashboard"))

    db = get_db()

    project = db.execute(
        """SELECT * FROM projects
        WHERE id=? AND staff_id=?""",
        (project_id, session["user_id"])
    ).fetchone()

    if not project:
        db.close()
        flash("Project not assigned to you.")
        return redirect(url_for("dashboard"))

    filename = secure_filename(
        f"project{project_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    )

    file.save(UPLOAD_FOLDER / filename)

    db.execute(
        """INSERT INTO proofs
        (project_id, staff_id, filename, note, uploaded_at)
        VALUES (?, ?, ?, ?, ?)""",
        (
            project_id,
            session["user_id"],
            filename,
            note,
            datetime.now().strftime("%d-%m-%Y %H:%M")
        )
    )

    db.commit()
    db.close()

    notify(
        project["client_id"],
        "New proof of work uploaded for " + project["title"]
    )

    flash("Proof uploaded successfully.")

    return redirect(url_for("dashboard"))


# 17. VIEW UPLOADED FILES
@app.route("/uploads/<filename>")
@login_required
def uploaded_file(filename):

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        filename
    )


# 17A. ADMIN APPROVES PROOF
@app.route("/admin/proof/<int:proof_id>/approve", methods=["POST"])
@login_required
@role_required("admin")
def approve_proof(proof_id):

    db = get_db()

    proof = db.execute(
        "SELECT * FROM proofs WHERE id=?",
        (proof_id,)
    ).fetchone()

    if proof:
        db.execute(
            "UPDATE proofs SET status='Approved' WHERE id=?",
            (proof_id,)
        )
        db.commit()
        db.close()

        notify(
            proof["staff_id"],
            "Your proof of work has been approved."
        )

        flash("Proof approved successfully.")

    else:
        db.close()
        flash("Proof not found.")

    return redirect(url_for("dashboard"))


# 17B. ADMIN REJECTS PROOF
@app.route("/admin/proof/<int:proof_id>/reject", methods=["POST"])
@login_required
@role_required("admin")
def reject_proof(proof_id):

    db = get_db()

    proof = db.execute(
        "SELECT * FROM proofs WHERE id=?",
        (proof_id,)
    ).fetchone()

    if proof:
        db.execute(
            "UPDATE proofs SET status='Rejected' WHERE id=?",
            (proof_id,)
        )
        db.commit()
        db.close()

        notify(
            proof["staff_id"],
            "Your proof of work has been rejected."
        )

        flash("Proof rejected.")

    else:
        db.close()
        flash("Proof not found.")

    return redirect(url_for("dashboard"))





# 18. CLIENT PAYMENT
@app.route("/project/<int:project_id>/pay", methods=["GET", "POST"])
@login_required
@role_required("user")
def pay(project_id):

    db = get_db()

    project = db.execute(
        """SELECT * FROM projects
        WHERE id=? AND client_id=?""",
        (project_id, session["user_id"])
    ).fetchone()

    if not project:
        db.close()
        flash("Project not found.")
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        amount = request.form.get("amount", type=float)
        method = request.form.get("method", "Cash")

        if amount and amount > 0:

            db.execute(
                """INSERT INTO payments
                (project_id, user_id, amount, method, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    session["user_id"],
                    amount,
                    method,
                    "Submitted",
                    datetime.now().strftime("%d-%m-%Y %H:%M")
                )
            )

            db.commit()
            db.close()

            notify(
                1,
                "New payment record submitted for " + project["title"]
            )

            flash("Payment record submitted. No real money was transferred.")

            return redirect(url_for("dashboard"))

        flash("Enter a valid amount.")

    db.close()

    return render_template("pay.html", project=project)


# 19. ADMIN PAYMENT MANAGEMENT
@app.route("/admin/payments")
@login_required
@role_required("admin")
def payments():

    db = get_db()

    payment_list = db.execute("""
        SELECT payments.*, projects.title,
        users.name AS client_name
        FROM payments
        JOIN projects ON payments.project_id=projects.id
        JOIN users ON payments.user_id=users.id
        ORDER BY payments.id DESC
    """).fetchall()

    db.close()

    return render_template(
        "payments.html",
        payments=payment_list
    )


# 20. APPROVE OR REJECT PAYMENT
@app.route("/admin/payment/<int:payment_id>/<action>", methods=["POST"])
@login_required
@role_required("admin")
def update_payment(payment_id, action):

    if action not in ["approve", "reject"]:
        return redirect(url_for("payments"))

    status = "Approved" if action == "approve" else "Rejected"

    db = get_db()

    payment = db.execute(
        "SELECT * FROM payments WHERE id=?",
        (payment_id,)
    ).fetchone()

    if payment:

        db.execute(
            "UPDATE payments SET status=? WHERE id=?",
            (status, payment_id)
        )

        db.commit()

        notify(
            payment["user_id"],
            "Your payment record was " + status.lower()
        )

    db.close()

    flash("Payment status updated.")

    return redirect(url_for("payments"))


# 21. PROJECT REPORTS
@app.route("/reports")
@login_required
@role_required("admin")
def reports():

    db = get_db()

    project_reports = db.execute(
        """SELECT status, COUNT(*) AS total
        FROM projects GROUP BY status"""
    ).fetchall()

    payment_total = db.execute(
        """SELECT COALESCE(SUM(amount), 0)
        FROM payments WHERE status='Approved'"""
    ).fetchone()[0]

    db.close()

    return render_template(
        "reports.html",
        projects=project_reports,
        payment_total=payment_total
    )


# 22. RUN THE APPLICATION
if __name__ == "__main__":

    init_db()

    app.run(debug=True)
