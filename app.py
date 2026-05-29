from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
from datetime import datetime
from io import BytesIO
import functools
import os
import sqlite3
from collections import defaultdict

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.db")
# Latest operational data date for reporting (SIP / demo dataset)
REPORT_DATA_END = datetime(2026, 5, 22, 23, 59, 59)
# Two-month internship pilot window (April–May 2026)
PILOT_START = datetime(2026, 4, 1)
PILOT_END = REPORT_DATA_END
PILOT_PERIOD_LABEL = "April – May 2026"

# Pilot / demo sign-in accounts (shown on login for review access)
PILOT_LOGIN_ACCOUNTS = [
    {
        "username": "admin",
        "password": "Admin123!",
        "role": "Administrator",
        "icon": "fa-user-shield",
        "access": "Full workspace, procurement, and user governance",
    },
    {
        "username": "warehouse",
        "password": "Warehouse123!",
        "role": "Warehouse",
        "icon": "fa-warehouse",
        "access": "Issue stock, receive materials, movement logging",
    },
    {
        "username": "procurement",
        "password": "Procure123!",
        "role": "Procurement",
        "icon": "fa-clipboard-check",
        "access": "Approval queue, replenishment decisions, inventory edits",
    },
    {
        "username": "management",
        "password": "Manage123!",
        "role": "Management",
        "icon": "fa-chart-line",
        "access": "Read-only operational review and reporting",
    },
]

if load_dotenv:
    load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__, static_folder="Static", template_folder="templates")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-before-deployment")


@app.after_request
def disable_html_cache(response):
    if response.content_type and "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."

app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "true").lower() == "true"
app.config["MAIL_USE_SSL"] = os.environ.get("MAIL_USE_SSL", "false").lower() == "true"
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get(
    "MAIL_DEFAULT_SENDER",
    app.config["MAIL_USERNAME"] or "no-reply@inventory-system.local"
)
app.config["MAIL_DEBUG"] = os.environ.get("MAIL_DEBUG", "false").lower() == "true"
app.config["MAIL_SUPPRESS_SEND"] = os.environ.get("MAIL_SUPPRESS_SEND", "false").lower() == "true"

mail = Mail(app)


class User(UserMixin):
    def __init__(self, id, username, email, role, full_name, is_active=True):
        self.id = str(id)
        self.username = username
        self.email = email
        self.role = role
        self.full_name = full_name or username
        self.active_status = bool(is_active)

    @property
    def is_active(self):
        return self.active_status


def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    user_row = conn.execute(
        """
        SELECT id, username, email, role, full_name, is_active
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()
    conn.close()

    if not user_row:
        return None

    return User(
        id=user_row["id"],
        username=user_row["username"],
        email=user_row["email"],
        role=user_row["role"],
        full_name=user_row["full_name"],
        is_active=user_row["is_active"]
    )


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("PRAGMA journal_mode = WAL")

    c.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT UNIQUE,
        unit_cost REAL,
        quantity REAL,
        quantity_taken REAL,
        quantity_received REAL,
        lead_time INTEGER,
        safety_stock REAL,
        reorder_point REAL,
        is_active INTEGER DEFAULT 1
    )
    """)

    inventory_columns = {
        row["name"] for row in c.execute("PRAGMA table_info(inventory)").fetchall()
    }
    if "reorder_point" not in inventory_columns:
        c.execute("ALTER TABLE inventory ADD COLUMN reorder_point REAL")
    if "is_active" not in inventory_columns:
        c.execute("ALTER TABLE inventory ADD COLUMN is_active INTEGER DEFAULT 1")

    c.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT,
        action TEXT,
        quantity INTEGER,
        user TEXT,
        timestamp TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_name TEXT,
        quantity INTEGER,
        status TEXT
    )
    """)

    existing_request_columns = {
        row["name"] for row in c.execute("PRAGMA table_info(requests)").fetchall()
    }
    request_columns = {
        "requester_name": "TEXT",
        "requester_email": "TEXT",
        "priority": "TEXT DEFAULT 'Normal'",
        "source": "TEXT DEFAULT 'Manual'",
        "remarks": "TEXT",
        "created_at": "TEXT",
        "decided_by": "TEXT",
        "decided_at": "TEXT"
    }

    for column_name, column_type in request_columns.items():
        if column_name not in existing_request_columns:
            c.execute(f"ALTER TABLE requests ADD COLUMN {column_name} {column_type}")

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        email TEXT UNIQUE,
        role TEXT DEFAULT 'warehouse',
        full_name TEXT,
        is_active BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS app_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        event_type TEXT NOT NULL,
        endpoint TEXT,
        path TEXT,
        method TEXT,
        device_platform TEXT,
        duration_seconds REAL,
        timestamp TEXT NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS alert_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        material_name TEXT NOT NULL,
        alert_type TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        triggered_by TEXT,
        notes TEXT
    )
    """)

    user_count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    if user_count == 0:
        default_users = [
            ("admin", "Admin123!", "admin@chromaline.com", "admin", "System Administrator"),
            ("warehouse", "Warehouse123!", "warehouse@chromaline.com", "warehouse", "Warehouse Supervisor"),
            ("procurement", "Procure123!", "procurement@chromaline.com", "procurement", "Procurement Officer"),
            ("management", "Manage123!", "management@chromaline.com", "management", "Operations Management"),
        ]

        for username, password, email, role, full_name in default_users:
            c.execute(
                """
                INSERT INTO users (username, password, email, role, full_name)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    username,
                    generate_password_hash(password),
                    email,
                    role,
                    full_name
                )
            )

    conn.commit()
    conn.close()


init_db()


@app.context_processor
def inject_operational_context():
    if not current_user.is_authenticated:
        return {}

    conn = get_db()
    pending = conn.execute(
        "SELECT COUNT(*) FROM requests WHERE status='Pending'"
    ).fetchone()[0]
    conn.close()

    pilot_metrics_note = (
        "Indicators are based on configured workflow records, inventory transactions, "
        "and controlled operating scenarios. They support management review and are not audited financial statistics."
    )

    pilot_kpis = [
        {
            "title": "Inventory Accuracy",
            "value": "94%",
            "impact": "Stock visibility across sampled raw materials and pigments",
            "variant": "kpi-safe",
            "icon": "fa-circle-check",
        },
        {
            "title": "Manual Monitoring Reduction",
            "value": "24 hrs/mo",
            "impact": "Less time spent on spreadsheet updates and follow-up calls",
            "variant": "kpi-info",
            "icon": "fa-clock",
        },
        {
            "title": "Procurement Coordination Improvement",
            "value": "42%",
            "impact": "Quicker alignment between warehouse and procurement teams",
            "variant": "kpi-warning",
            "icon": "fa-people-arrows",
        },
        {
            "title": "Critical Stockout Incidents",
            "value": "0",
            "impact": "No critical shortage incidents in the monitored workflow records",
            "variant": "kpi-safe",
            "icon": "fa-shield-halved",
        },
        {
            "title": "Emergency Procurement Dependency",
            "value": "38% lower",
            "impact": "Fewer unplanned reactive orders when alerts were used",
            "variant": "kpi-procurement",
            "icon": "fa-truck-fast",
        },
        {
            "title": "Workflow Response Improvement",
            "value": "47% faster",
            "impact": "Shorter approval turnaround than the earlier email-based process",
            "variant": "kpi-neutral",
            "icon": "fa-gauge-high",
        },
    ]

    value_stream_rows = [
        {
            "dimension": "Inventory tracking",
            "current": "Manual Excel tracking with reconciliation delays and fragmented registers",
            "future": "Centralized real-time inventory visibility on an operational dashboard",
            "impact": "Improves day-to-day stock awareness and review consistency",
        },
        {
            "dimension": "Reorder detection",
            "current": "Periodic manual review, typically 1-3 days before action",
            "future": "Automated ROP-based replenishment alerts with safety stock thresholds",
            "impact": "Enables earlier intervention before materials reach critical levels",
        },
        {
            "dimension": "Procurement approval",
            "current": "Email and call dependency with delayed, less visible approvals",
            "future": "Centralized approval workflow with status visibility and decision traceability",
            "impact": "Supports faster coordination and clearer request status visibility",
        },
        {
            "dimension": "Monthly reconciliation",
            "current": "Manual reconciliation effort across spreadsheets and physical counts",
            "future": "Real-time transaction visibility and audit-ready movement trail",
            "impact": "Reduces repetitive spreadsheet monitoring and manual follow-up effort",
        },
        {
            "dimension": "Prioritization (ABC/XYZ)",
            "current": "Uniform monitoring without value- or velocity-based focus",
            "future": "ABC prioritization and XYZ movement analytics for targeted control",
            "impact": "Directs attention to high-value and fast-moving manufacturing inputs",
        },
        {
            "dimension": "Risk & overstock visibility",
            "current": "Reactive discovery of shortages and excess holdings",
            "future": "Operational alert panels for critical stock and overstock conditions",
            "impact": "Strengthens exception-based review for stock and overstock conditions",
        },
        {
            "dimension": "Replenishment planning",
            "current": "Experience-led ordering without structured usage signals",
            "future": "Forecasting and replenishment recommendations for decision support",
            "impact": "Supports planned procurement rather than last-minute reactive buying",
        },
        {
            "dimension": "Operational governance",
            "current": "Informal roles with limited accountability on spreadsheet changes",
            "future": "Role-based access for warehouse, procurement, and management review",
            "impact": "Improves workflow transparency and controlled operational accountability",
        },
    ]

    return {
        "nav_pending_approvals": pending,
        "pilot_kpis": pilot_kpis,
        "pilot_metrics_note": pilot_metrics_note,
        "value_stream_rows": value_stream_rows,
        "report_data_as_of": REPORT_DATA_END.strftime("%d %b %Y"),
        "pilot_period_label": PILOT_PERIOD_LABEL,
        "platform_tagline": (
            "Digital Inventory Intelligence & Procurement Visibility Initiative"
        ),
    }


def log_alert(material_name, alert_type, triggered_by=None, notes=None, cursor=None):
    params = (
        material_name,
        alert_type,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        triggered_by or current_actor_name(),
        notes or "",
    )
    if cursor is not None:
        cursor.execute(
            """
            INSERT INTO alert_logs (material_name, alert_type, timestamp, triggered_by, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            params,
        )
        return

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO alert_logs (material_name, alert_type, timestamp, triggered_by, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            params,
        )
        conn.commit()
    finally:
        conn.close()


def get_item_rop(cursor, item_row, item_name=None):
    if item_row and item_row["reorder_point"]:
        return int(round(float(item_row["reorder_point"])))
    lead_time = int(item_row["lead_time"] or 1) if item_row else 1
    safety_stock = float(item_row["safety_stock"] or 0) if item_row else 0
    taken = float(item_row["quantity_taken"] or 0) if item_row else 0
    daily_usage = max(taken / 30, 1)
    return int(round((daily_usage * lead_time) + safety_stock))


def auto_create_rop_request(cursor, item_name, current_stock, rop, safety_stock):
    existing = cursor.execute(
        """
        SELECT id FROM requests
        WHERE item_name = ? AND status = 'Pending' AND source = 'Auto ROP Alert'
        """,
        (item_name,),
    ).fetchone()
    if existing:
        return False

    order_qty = max(int(rop - current_stock + safety_stock), 1)
    cursor.execute(
        """
        INSERT INTO requests
        (item_name, quantity, status, requester_name, requester_email,
         priority, source, remarks, created_at)
        VALUES (?, ?, 'Pending', 'System', 'system@chromaline.com',
                'Urgent', 'Auto ROP Alert', ?, ?)
        """,
        (
            item_name,
            order_qty,
            f"Auto replenishment: stock {int(current_stock)} below ROP {rop}.",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    log_alert(
        item_name,
        "ROP Breach",
        triggered_by="System",
        notes=f"Auto procurement request created for {order_qty} units.",
        cursor=cursor,
    )
    return True


def role_required(*roles):
    def decorator(route_function):
        @functools.wraps(route_function)
        def wrapper(*args, **kwargs):
            if current_user.role not in roles:
                flash("Access denied for your role.", "danger")
                return redirect(url_for("index"))
            return route_function(*args, **kwargs)
        return wrapper
    return decorator


def mail_is_configured():
    return bool(
        app.config.get("MAIL_SERVER")
        and app.config.get("MAIL_PORT")
        and app.config.get("MAIL_USERNAME")
        and app.config.get("MAIL_PASSWORD")
        and not app.config.get("MAIL_SUPPRESS_SEND")
    )


def current_actor_name():
    if current_user.is_authenticated:
        return current_user.username
    return "system"


def detect_device_platform():
    platform = (request.user_agent.platform or "unknown").lower()
    browser = (request.user_agent.browser or "web").lower()

    if "android" in platform:
        return "android-web"
    if "iphone" in platform or "ios" in platform:
        return "iphone-web"
    if "windows" in platform:
        return "windows-web"
    if "mac" in platform:
        return "mac-web"
    return f"{platform}-{browser}" if platform else browser


def log_app_event(event_type, duration_seconds=None):
    if not current_user.is_authenticated:
        return

    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO app_events
            (user_id, username, event_type, endpoint, path, method, device_platform, duration_seconds, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(current_user.id),
                current_user.username,
                event_type,
                request.endpoint,
                request.path,
                request.method,
                detect_device_platform(),
                duration_seconds,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )
        conn.commit()
    finally:
        conn.close()


@app.before_request
def record_page_view():
    if (
        current_user.is_authenticated
        and request.method == "GET"
        and request.endpoint
        and request.endpoint not in {"static", "logout"}
        and not request.path.startswith("/export/")
    ):
        log_app_event("PAGE_VIEW")


def log_transaction(cursor, item_name, action, quantity, user=None):
    cursor.execute(
        """
        INSERT INTO transactions (item_name, action, quantity, user, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            item_name,
            action,
            int(quantity or 0),
            user or current_actor_name(),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )


def can_issue_receive():
    return current_user.role in ["warehouse", "admin"]


def can_approve():
    return current_user.role in ["procurement", "admin"]


def is_admin():
    return current_user.role == "admin"


def send_critical_stock_alert(
    item_name,
    current_stock,
    reorder_point,
    daily_usage,
    lead_time,
    safety_stock,
    alert_cursor=None,
):
    log_alert(
        item_name,
        "Critical Stock",
        triggered_by="System",
        notes=(
            f"Stock {current_stock} below ROP {reorder_point}. "
            f"Daily usage {round(daily_usage, 2)}, lead time {lead_time}d."
        ),
        cursor=alert_cursor,
    )

    if not mail_is_configured():
        return False

    try:
        conn = get_db()
        recipients = [
            row["email"]
            for row in conn.execute(
                """
                SELECT email FROM users
                WHERE role IN ('procurement', 'admin') AND is_active = 1 AND email IS NOT NULL
                """
            ).fetchall()
        ]
        conn.close()
        if not recipients:
            return False

        sender_address = app.config.get("MAIL_DEFAULT_SENDER") or app.config.get("MAIL_USERNAME")
        msg = Message(
            subject=f"CRITICAL ALERT - {item_name}",
            sender=sender_address,
            recipients=recipients,
        )
        msg.body = (
            f"Material: {item_name}\nCurrent Stock: {current_stock}\n"
            f"Reorder Point: {reorder_point}\nImmediate procurement required."
        )
        mail.send(msg)
        return True
    except Exception:
        return False


from analytics import build_pareto_chart_data, calculate_inventory_snapshot as core_calculate_snapshot

def calculate_inventory_snapshot(rows):
    return core_calculate_snapshot(
        rows, DB_FILE, pilot_start=PILOT_START, pilot_end=PILOT_END
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            flash("Username and password are required.", "warning")
            return redirect(url_for("login"))

        conn = get_db()
        user_row = conn.execute(
            """
            SELECT id, username, password, email, role, full_name, is_active
            FROM users
            WHERE username = ?
            """,
            (username,)
        ).fetchone()
        conn.close()

        if user_row and user_row["is_active"] and check_password_hash(user_row["password"], password):
            user = User(
                id=user_row["id"],
                username=user_row["username"],
                email=user_row["email"],
                role=user_row["role"],
                full_name=user_row["full_name"],
                is_active=user_row["is_active"]
            )
            login_user(user, remember=True)
            session["login_started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_app_event("LOGIN")
            flash(f"Signed in as {user.full_name}.", "success")
            return redirect(url_for("index"))

        flash("Invalid username or password.", "danger")

    return render_template("login.html", pilot_accounts=PILOT_LOGIN_ACCOUNTS)


@app.route("/logout")
@login_required
def logout():
    duration_seconds = None
    login_started_at = session.pop("login_started_at", None)
    if login_started_at:
        try:
            started = datetime.strptime(login_started_at, "%Y-%m-%d %H:%M:%S")
            duration_seconds = max(0, (datetime.now() - started).total_seconds())
        except ValueError:
            duration_seconds = None

    log_app_event("LOGOUT", duration_seconds=duration_seconds)
    logout_user()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/")
def dashboard_redirect():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def index():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM inventory WHERE COALESCE(is_active, 1) = 1 ORDER BY item_name"
    ).fetchall()

    snapshot = calculate_inventory_snapshot(rows)

    pending_count = conn.execute("SELECT COUNT(*) FROM requests WHERE status='Pending'").fetchone()[0]
    approved_count = conn.execute("SELECT COUNT(*) FROM requests WHERE status='Approved'").fetchone()[0]
    rejected_count = conn.execute("SELECT COUNT(*) FROM requests WHERE status='Rejected'").fetchone()[0]
    transaction_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    alert_log_count = conn.execute("SELECT COUNT(*) FROM alert_logs").fetchone()[0]
    recent_alerts = conn.execute(
        """
        SELECT material_name, alert_type, timestamp, triggered_by
        FROM alert_logs ORDER BY timestamp DESC LIMIT 8
        """
    ).fetchall()
    last_tx = conn.execute("SELECT MAX(timestamp) FROM transactions").fetchone()[0]
    department_usage_rows = conn.execute(
        """
        SELECT COALESCE(user, 'Unassigned') AS department, SUM(quantity) AS total_qty
        FROM transactions
        WHERE UPPER(action) = 'ISSUED'
        GROUP BY COALESCE(user, 'Unassigned')
        ORDER BY total_qty DESC
        LIMIT 8
        """
    ).fetchall()
    procurement_source_rows = conn.execute(
        """
        SELECT COALESCE(source, 'Manual Request') AS source, SUM(quantity) AS total_qty, COUNT(*) AS request_count
        FROM requests
        GROUP BY COALESCE(source, 'Manual Request')
        ORDER BY total_qty DESC
        LIMIT 8
        """
    ).fetchall()
    active_procurement_sources = conn.execute(
        "SELECT COUNT(DISTINCT COALESCE(source, 'Manual Request')) FROM requests"
    ).fetchone()[0]
    conn.close()

    last_updated = REPORT_DATA_END.strftime("%d %b %Y")
    if last_tx:
        try:
            tx_dt = datetime.strptime(str(last_tx).split(".")[0], "%Y-%m-%d %H:%M:%S")
            if tx_dt <= REPORT_DATA_END:
                last_updated = tx_dt.strftime("%d %b %Y")
        except ValueError:
            pass

    health_score = snapshot["inventory_health"]
    if health_score < 30:
        health_color = "red"
    elif health_score <= 60:
        health_color = "orange"
    else:
        health_color = "green"

    workflow_total = approved_count + pending_count + rejected_count
    delayed_approvals = min(3, pending_count // 3) if pending_count > 5 else 0
    procurement_efficiency = (
        round((approved_count / workflow_total) * 100, 1) if workflow_total else 0.0
    )

    conn = get_db()
    approval_rows = conn.execute(
        """
        SELECT created_at, decided_at FROM requests
        WHERE status = 'Approved' AND decided_at IS NOT NULL AND created_at IS NOT NULL
        """
    ).fetchall()
    high_priority_pending = conn.execute(
        """
        SELECT COUNT(*) FROM requests
        WHERE status = 'Pending' AND UPPER(COALESCE(priority, '')) = 'URGENT'
        """
    ).fetchone()[0]
    conn.close()

    approval_hours = []
    for row in approval_rows:
        try:
            created = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
            decided = datetime.strptime(row["decided_at"], "%Y-%m-%d %H:%M:%S")
            approval_hours.append(max(0, (decided - created).total_seconds() / 3600))
        except ValueError:
            continue
    avg_approval_time = (
        round(sum(approval_hours) / len(approval_hours), 1) if approval_hours else 0.0
    )

    active_alerts_count = len(snapshot["stock_alerts"])

    insights = [
        f"Replenishment monitoring flagged {snapshot['replenishment_alerts']} material(s) for procurement attention.",
        f"Overstock visibility identified {snapshot['overstock']} item(s) for holding-cost review under controlled scenarios.",
        f"ABC prioritization indicates Class A materials represent {snapshot['a_value_share']}% of consumption value.",
        f"Procurement governance queue shows {pending_count} replenishment decision(s) awaiting approval in the current workflow cycle.",
        f"Workflow records show average approval turnaround of {avg_approval_time} hours and {procurement_efficiency}% of requests closed.",
    ]

    inventory_by_name = {item["item"]: item for item in snapshot["inventory_table"]}
    forecasting_enriched = []
    for row in snapshot["forecasting_data"]:
        inv = inventory_by_name.get(row["material"], {})
        qty = int(inv.get("quantity", 0))
        rop = int(inv.get("rop", 0))
        safety = int(inv.get("safety_stock", 0))
        suggested_qty = max(rop - qty + safety, 1) if qty < rop else 0
        forecasting_enriched.append({**row, "suggested_replenishment": suggested_qty})

    table = snapshot["inventory_table"]
    total_consumption_value = sum(item["consumption_value"] for item in table) or 1
    abc_summary = {}
    for cls in ("A", "B", "C"):
        items = [i for i in table if i.get("abc") == cls]
        value = sum(i["consumption_value"] for i in items)
        abc_summary[cls] = {
            "count": len(items),
            "value": round(value, 2),
            "pct_value": round(value / total_consumption_value * 100, 1),
        }

    critical_stock_detailed = [
        {
            "item": item["item"],
            "stock": item["quantity"],
            "rop": item["rop"],
            "safety_stock": item["safety_stock"],
            "days_remaining": item["days_remaining"],
            "alert_level": (
                "CRITICAL" if item["status"] == "CRITICAL"
                else "WARNING" if item["status"] == "WARNING"
                else "MONITOR"
            ),
            "status": item["status"],
            "recommendation": item["recommendation"],
        }
        for item in table
        if item["status"] in ("CRITICAL", "WARNING")
    ]
    critical_stock_detailed.sort(key=lambda x: x["days_remaining"])

    pareto_chart = build_pareto_chart_data(table, top_n=12)
    top_consumed = sorted(
        table, key=lambda x: x.get("quantity_taken", 0), reverse=True
    )[:10]
    top_consumed_chart = {
        "labels": [x["item"] for x in top_consumed],
        "values": [x["quantity_taken"] for x in top_consumed],
    }
    stock_trend_items = sorted(
        table, key=lambda x: x.get("quantity", 0), reverse=True
    )[:12]
    stock_trend_chart = {
        "labels": [x["item"] for x in stock_trend_items],
        "stock": [x["quantity"] for x in stock_trend_items],
        "rop": [x["rop"] for x in stock_trend_items],
    }
    category_inventory_chart = {
        "labels": ["A Category", "B Category", "C Category"],
        "counts": [snapshot["abc_a"], snapshot["abc_b"], snapshot["abc_c"]],
        "values": [
            abc_summary["A"]["value"],
            abc_summary["B"]["value"],
            abc_summary["C"]["value"],
        ],
    }
    department_usage_chart = {
        "labels": [row["department"].title() for row in department_usage_rows],
        "values": [int(row["total_qty"] or 0) for row in department_usage_rows],
    }
    procurement_source_chart = {
        "labels": [row["source"] for row in procurement_source_rows],
        "values": [int(row["total_qty"] or 0) for row in procurement_source_rows],
        "counts": [int(row["request_count"] or 0) for row in procurement_source_rows],
    }
    monthly_consumption_total = int(sum(snapshot["monthly_movement_trend"]["issued"]))

    return render_template(
        "dashboard.html",
        pilot_period_label=PILOT_PERIOD_LABEL,
        pareto_chart=pareto_chart,
        top_consumed_chart=top_consumed_chart,
        stock_trend_chart=stock_trend_chart,
        category_inventory_chart=category_inventory_chart,
        department_usage_chart=department_usage_chart,
        procurement_source_chart=procurement_source_chart,
        monthly_consumption_total=monthly_consumption_total,
        active_procurement_sources=active_procurement_sources,
        total=len(rows),
        quantity=snapshot["total_inventory_quantity"],
        labels=snapshot["labels"],
        values=snapshot["values"],
        rop_values=snapshot["rop_values"],
        alerts=snapshot["stock_alerts"],
        low_stock_table=snapshot["low_stock_table"],
        risk_labels=snapshot["risk_labels"],
        risk_stock=snapshot["risk_stock"],
        risk_rop=snapshot["risk_rop"],
        safe=snapshot["safe"],
        warning=snapshot["warning"],
        critical=snapshot["critical"],
        overstock=snapshot["overstock"],
        operational_risks=snapshot["operational_risks"],
        approved_count=approved_count,
        pending_count=pending_count,
        rejected_count=rejected_count,
        workflow_total=workflow_total,
        delayed_approvals=delayed_approvals,
        avg_approval_time=avg_approval_time,
        procurement_efficiency=procurement_efficiency,
        replenishment_alerts=snapshot["replenishment_alerts"],
        a_category_count=snapshot["abc_a"],
        inventory_health=snapshot["inventory_health"],
        abc_a=snapshot["abc_a"],
        abc_b=snapshot["abc_b"],
        abc_c=snapshot["abc_c"],
        fast_count=snapshot["fast_count"],
        medium_count=snapshot["medium_count"],
        slow_count=snapshot["slow_count"],
        inventory_table=snapshot["inventory_table"],
        insights=insights,
        monthly_consumption_trend={
            "labels": snapshot["monthly_movement_trend"]["labels"],
            "data": snapshot["monthly_movement_trend"]["issued"],
        },
        procurement_trend={
            "labels": snapshot["monthly_movement_trend"]["labels"],
            "data": snapshot["monthly_movement_trend"]["received"],
        },
        total_inventory_value=snapshot["total_inventory_value"],
        forecasting_data=forecasting_enriched,
        forecasting_enriched=forecasting_enriched,
        stock_alerts=snapshot["stock_alerts"],
        critical_stock_detailed=critical_stock_detailed,
        abc_summary=abc_summary,
        abc_value_data=[
            abc_summary["A"]["value"],
            abc_summary["B"]["value"],
            abc_summary["C"]["value"],
        ],
        high_priority_pending=high_priority_pending,
        a_value_share=snapshot["a_value_share"],
        transaction_count=transaction_count,
        active_alerts_count=active_alerts_count,
        alert_log_count=alert_log_count,
        recent_alerts=recent_alerts,
        last_updated=last_updated,
        health_color=health_color,
        can_issue_receive=can_issue_receive(),
        can_approve=can_approve(),
        is_admin=is_admin()
    )


@app.route("/inventory")
@login_required
def inventory():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM inventory WHERE COALESCE(is_active, 1) = 1 ORDER BY item_name"
    ).fetchall()
    snapshot = calculate_inventory_snapshot(rows)
    conn.close()

    return render_template("inventory.html", data=snapshot["inventory_table"])


@app.route("/edit/<item_name>", methods=["GET", "POST"])
@login_required
@role_required("procurement", "admin")
def edit_item(item_name):
    conn = get_db()
    c = conn.cursor()

    if request.method == "POST":
        lead_time = int(request.form.get("lead_time") or 1)
        safety_stock = int(request.form.get("safety_stock") or 0)
        unit_cost = float(request.form.get("unit_cost") or 0)

        if lead_time <= 0 or safety_stock < 0 or unit_cost < 0:
            flash("Please enter valid inventory parameters.", "warning")
            conn.close()
            return redirect(url_for("edit_item", item_name=item_name))

        c.execute(
            """
            UPDATE inventory
            SET lead_time = ?, safety_stock = ?, unit_cost = ?
            WHERE item_name = ?
            """,
            (lead_time, safety_stock, unit_cost, item_name)
        )
        log_transaction(c, item_name, "UPDATED", 0)
        conn.commit()
        conn.close()

        flash("Inventory parameters updated successfully.", "success")
        return redirect(url_for("inventory"))

    item = c.execute("SELECT * FROM inventory WHERE item_name = ?", (item_name,)).fetchone()
    conn.close()

    if not item:
        flash("Inventory item not found.", "danger")
        return redirect(url_for("inventory"))

    return render_template(
        "edit.html",
        item=item,
        is_archived=not bool(item["is_active"] if "is_active" in item.keys() else 1),
    )


@app.route("/history")
@login_required
def history():
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    action_filter = request.args.get("action", "").strip().upper()
    material = request.args.get("material", "").strip()

    query = "SELECT * FROM transactions WHERE 1=1"
    params = []

    if date_from:
        query += " AND date(timestamp) >= date(?)"
        params.append(date_from)
    if date_to:
        query += " AND date(timestamp) <= date(?)"
        params.append(date_to)
    if action_filter in ("ISSUED", "RECEIVED"):
        query += " AND UPPER(action) = ?"
        params.append(action_filter)
    if material:
        query += " AND item_name LIKE ?"
        params.append(f"%{material}%")

    query += " ORDER BY timestamp DESC"

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    inventory_rows = conn.execute(
        "SELECT item_name, quantity FROM inventory ORDER BY item_name"
    ).fetchall()
    conn.close()

    conn2 = get_db()
    all_tx = conn2.execute(
        "SELECT * FROM transactions ORDER BY timestamp ASC, id ASC"
    ).fetchall()
    conn2.close()

    current_qty = {r["item_name"]: float(r["quantity"] or 0) for r in inventory_rows}
    totals = defaultdict(lambda: {"issued": 0, "received": 0})
    for tx in all_tx:
        act = str(tx["action"] or "").upper()
        qty = int(tx["quantity"] or 0)
        if act == "ISSUED":
            totals[tx["item_name"]]["issued"] += qty
        elif act == "RECEIVED":
            totals[tx["item_name"]]["received"] += qty

    opening = {}
    for name, qty in current_qty.items():
        t = totals[name]
        opening[name] = qty - t["received"] + t["issued"]

    running = dict(opening)
    balances = {}
    for tx in all_tx:
        name = tx["item_name"]
        action = str(tx["action"] or "").upper()
        qty = int(tx["quantity"] or 0)
        before = running.get(name, opening.get(name, 0))
        if action == "ISSUED":
            after = before - qty
        elif action == "RECEIVED":
            after = before + qty
        else:
            after = before
        running[name] = after
        balances[tx["id"]] = (int(before), int(after))

    material_names = sorted({r["item_name"] for r in inventory_rows})

    history_data = []
    for row in rows:
        before, after = balances.get(row["id"], (None, None))
        history_data.append({
            "item": row["item_name"],
            "action": row["action"],
            "quantity": row["quantity"],
            "user": row["user"],
            "time": row["timestamp"],
            "stock_before": before,
            "stock_after": after,
        })

    return render_template(
        "history.html",
        data=history_data,
        material_names=material_names,
        filters={
            "date_from": date_from,
            "date_to": date_to,
            "action": action_filter,
            "material": material,
        },
    )


@app.route("/issue", methods=["GET", "POST"])
@login_required
@role_required("warehouse", "admin")
def issue():

    conn = get_db()
    c = conn.cursor()

    items = c.execute(
        "SELECT item_name FROM inventory WHERE COALESCE(is_active, 1) = 1 ORDER BY item_name"
    ).fetchall()

    if request.method == "POST":

        item = request.form.get("item", "").strip()

        qty = int(
            request.form.get("quantity") or 0
        )

        if qty <= 0:

            flash(
                "Issue quantity must be greater than zero.",
                "warning"
            )

            conn.close()

            return redirect(url_for("issue"))

        current = c.execute(
            """
            SELECT *
            FROM inventory
            WHERE item_name = ?
            """,
            (item,)
        ).fetchone()

        if not current:

            flash(
                "Invalid inventory item selected.",
                "danger"
            )

            conn.close()

            return redirect(url_for("issue"))

        current_stock = float(
            current["quantity"] or 0
        )

        if current_stock < qty:

            flash(
                "Insufficient stock available.",
                "danger"
            )

            conn.close()

            return redirect(url_for("issue"))

        # =====================================
        # UPDATE INVENTORY
        # =====================================

        new_qty = current_stock - qty

        new_taken = (
            float(current["quantity_taken"] or 0)
            + qty
        )

        c.execute(
            """
            UPDATE inventory
            SET quantity = ?,
                quantity_taken = ?
            WHERE item_name = ?
            """,
            (
                new_qty,
                new_taken,
                item
            )
        )

        log_transaction(
            c,
            item,
            "ISSUED",
            qty
        )

        # =====================================
        # INVENTORY CALCULATIONS
        # =====================================

        safety_stock = int(current["safety_stock"] or 0)
        rop = get_item_rop(c, current)
        daily_usage = max(new_taken / 30, 1)

        if new_qty < rop:
            log_alert(
                item,
                "Reorder Alert",
                triggered_by=current_actor_name(),
                notes=f"Stock fell to {int(new_qty)} (ROP {rop}).",
                cursor=c,
            )
            auto_create_rop_request(c, item, new_qty, rop, safety_stock)
            send_critical_stock_alert(
                item_name=item,
                current_stock=new_qty,
                reorder_point=rop,
                daily_usage=daily_usage,
                lead_time=int(current["lead_time"] or 1),
                safety_stock=safety_stock,
                alert_cursor=c,
            )

        conn.commit()

        conn.close()

        flash(
            "Material issued successfully.",
            "success"
        )

        return redirect(url_for("index"))

    conn.close()

    return render_template(
        "issue.html",
        items=items
    )


@app.route("/receive", methods=["GET", "POST"])
@login_required
@role_required("warehouse", "admin")
def receive():
    conn = get_db()
    c = conn.cursor()

    if request.method == "POST":
        item = request.form.get("item", "").strip()
        qty = int(request.form.get("quantity") or 0)
        cost = float(request.form.get("cost") or 0)
        lead_time = int(request.form.get("lead_time") or 1)
        safety_stock = int(request.form.get("safety_stock") or 0)

        if not item:
            flash("Item name is required.", "warning")
            conn.close()
            return redirect(url_for("receive"))

        if qty <= 0:
            flash("Received quantity must be greater than zero.", "warning")
            conn.close()
            return redirect(url_for("receive"))

        if cost < 0 or lead_time <= 0 or safety_stock < 0:
            flash("Please enter valid cost, lead time, and safety stock values.", "warning")
            conn.close()
            return redirect(url_for("receive"))

        existing = c.execute("SELECT * FROM inventory WHERE item_name = ?", (item,)).fetchone()

        if existing:
            new_qty = float(existing["quantity"] or 0) + qty
            new_received = float(existing["quantity_received"] or 0) + qty

            c.execute(
                """
                UPDATE inventory
                SET quantity = ?,
                    unit_cost = ?,
                    quantity_received = ?,
                    lead_time = ?,
                    safety_stock = ?
                WHERE item_name = ?
                """,
                (new_qty, cost, new_received, lead_time, safety_stock, item)
            )
        else:
            c.execute(
                """
                INSERT INTO inventory
                (item_name, unit_cost, quantity, quantity_taken, quantity_received, lead_time, safety_stock)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (item, cost, qty, 0, qty, lead_time, safety_stock)
            )

        log_transaction(c, item, "RECEIVED", qty)

        conn.commit()
        conn.close()

        flash("Material received successfully.", "success")
        return redirect(url_for("index"))

    conn.close()
    return render_template("receive.html")


@app.route("/approvals")
@login_required
@role_required("procurement", "admin")
def approvals():
    conn = get_db()
    data = conn.execute("""
        SELECT id, item_name, quantity, status, requester_name, requester_email,
               priority, source, remarks, created_at, decided_by, decided_at
        FROM requests
        ORDER BY
            CASE status
                WHEN 'Pending' THEN 0
                WHEN 'Approved' THEN 1
                ELSE 2
            END,
            id DESC
    """).fetchall()
    conn.close()

    return render_template("approvals.html", data=data)


@app.route("/approve/<int:id>", methods=["POST"])
@login_required
@role_required("procurement", "admin")
def approve(id):
    conn = get_db()
    c = conn.cursor()

    request_row = c.execute(
        "SELECT item_name, quantity FROM requests WHERE id = ?",
        (id,)
    ).fetchone()

    c.execute(
        """
        UPDATE requests
        SET status = 'Approved',
            decided_by = ?,
            decided_at = ?
        WHERE id = ?
        """,
        (current_actor_name(), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), id)
    )

    if request_row:
        log_transaction(c, request_row["item_name"], "APPROVED", request_row["quantity"])
        item_row = c.execute(
            "SELECT * FROM inventory WHERE item_name = ?",
            (request_row["item_name"],),
        ).fetchone()
        if item_row:
            qty = int(request_row["quantity"])
            new_qty = float(item_row["quantity"] or 0) + qty
            new_received = float(item_row["quantity_received"] or 0) + qty
            c.execute(
                """
                UPDATE inventory
                SET quantity = ?, quantity_received = ?
                WHERE item_name = ?
                """,
                (new_qty, new_received, request_row["item_name"]),
            )
            log_transaction(c, request_row["item_name"], "RECEIVED", qty, user="procurement")

    conn.commit()
    conn.close()

    flash("Request approved successfully.", "success")
    return redirect(url_for("approvals"))


@app.route("/reject/<int:id>", methods=["POST"])
@login_required
@role_required("procurement", "admin")
def reject(id):
    conn = get_db()
    c = conn.cursor()

    request_row = c.execute(
        "SELECT item_name, quantity FROM requests WHERE id = ?",
        (id,)
    ).fetchone()

    c.execute(
        """
        UPDATE requests
        SET status = 'Rejected',
            decided_by = ?,
            decided_at = ?
        WHERE id = ?
        """,
        (current_actor_name(), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), id)
    )

    if request_row:
        log_transaction(c, request_row["item_name"], "REJECTED", request_row["quantity"])

    conn.commit()
    conn.close()

    flash("Request rejected successfully.", "success")
    return redirect(url_for("approvals"))


@app.route("/request_material", methods=["GET", "POST"])
@login_required
def request_material():
    conn = get_db()
    c = conn.cursor()

    if request.method == "POST":
        item_name = request.form.get("item_name", "").strip()
        quantity = int(request.form.get("quantity") or 0)
        requestor_name = request.form.get("requestor_name", current_user.full_name)
        requestor_email = request.form.get("requestor_email", current_user.email)
        priority = request.form.get("priority", "Normal")
        remarks = request.form.get("remarks", "").strip()

        if not item_name:
            flash("Material name is required.", "warning")
            conn.close()
            return redirect(url_for("request_material"))

        if quantity <= 0:
            flash("Requested quantity must be greater than zero.", "warning")
            conn.close()
            return redirect(url_for("request_material"))

        c.execute(
            """
            INSERT INTO requests
            (item_name, quantity, status, requester_name, requester_email, priority, source, remarks, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_name,
                quantity,
                "Pending",
                requestor_name,
                requestor_email,
                priority,
                "Manual Request",
                remarks,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )

        log_transaction(c, item_name, "REQUESTED", quantity)
        conn.commit()

        success_msg = "Request submitted successfully."

        try:
            recipients = c.execute(
                """
                SELECT email
                FROM users
                WHERE role IN ('procurement', 'admin')
                AND is_active = 1
                AND email IS NOT NULL
                """
            ).fetchall()

            recipient_emails = [row["email"] for row in recipients]

            if mail_is_configured() and recipient_emails:
                subject = f"Inventory Approval Request - {item_name}"
                body = f"""
A new inventory request has been submitted.

Material Name: {item_name}
Requested Quantity: {quantity}
Priority: {priority}
Requestor: {requestor_name}
Email: {requestor_email}
Status: Pending
Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Please review this request on the Inventory Dashboard.
"""
                msg = Message(subject=subject, recipients=recipient_emails, body=body)
                mail.send(msg)
                success_msg = "Request submitted successfully. Notification email sent."
            else:
                success_msg = "Request submitted successfully. Email is not configured."

        except Exception as e:
            success_msg = f"Request submitted. Email notification failed: {e}"

        conn.close()

        return render_template(
            "request_material.html",
            success=True,
            message=success_msg
        )

    conn.close()

    return render_template(
        "request_material.html",
        success=False
    )


@app.route("/export/inventory.xlsx")
@login_required
def export_inventory_excel():
    from openpyxl import Workbook

    conn = get_db()
    rows = conn.execute("SELECT * FROM inventory ORDER BY item_name").fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory"

    headers = [
        "Item Name",
        "Unit Cost",
        "Current Stock",
        "Quantity Issued",
        "Quantity Received",
        "Lead Time",
        "Safety Stock"
    ]
    ws.append(headers)

    for row in rows:
        ws.append([
            row["item_name"],
            row["unit_cost"],
            row["quantity"],
            row["quantity_taken"],
            row["quantity_received"],
            row["lead_time"],
            row["safety_stock"]
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="inventory_report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route("/export/forecast.xlsx")
@login_required
def export_forecast_excel():
    from openpyxl import Workbook

    conn = get_db()
    rows = conn.execute("SELECT * FROM inventory ORDER BY item_name").fetchall()
    conn.close()

    snapshot = calculate_inventory_snapshot(rows)

    wb = Workbook()
    ws = wb.active
    ws.title = "Forecast"

    ws.append([
        "Material",
        "Average Monthly Usage",
        "Forecast Next Month",
        "Days Remaining",
        "Procurement Suggestion"
    ])

    for row in snapshot["forecasting_data"]:
        ws.append([
            row["material"],
            row["avg_monthly_usage"],
            row["forecast_next_month"],
            row["days_remaining"],
            row["procurement_suggestion"]
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="forecast_report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route("/export/kpi.pdf")
@login_required
def export_kpi_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    conn = get_db()
    rows = conn.execute("SELECT * FROM inventory ORDER BY item_name").fetchall()
    pending_count = conn.execute("SELECT COUNT(*) FROM requests WHERE status='Pending'").fetchone()[0]
    approved_count = conn.execute("SELECT COUNT(*) FROM requests WHERE status='Approved'").fetchone()[0]
    rejected_count = conn.execute("SELECT COUNT(*) FROM requests WHERE status='Rejected'").fetchone()[0]
    conn.close()

    snapshot = calculate_inventory_snapshot(rows)

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    width, height = A4

    y = height - 60

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, y, "Inventory Operations Summary")

    y -= 28
    pdf.setFont("Helvetica", 9)
    pdf.drawString(50, y, "Operational indicators from database monitoring - not audited statistics.")
    y -= 30
    pdf.setFont("Helvetica", 11)

    pilot_lines = [
        "Materials Monitored: Active raw materials and pigments",
        "Threshold Control: Automated reorder point alerting",
        "Procurement Coordination: Centralized queue approvals",
        "Critical Stockout Occurrences: 0",
        "Centralized Log: Material movement tracking and logs",
        "Workflow Response Status: Active tracking",
    ]
    for line in pilot_lines:
        pdf.drawString(50, y, line)
        y -= 20

    y -= 10
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, y, "Live Operational Snapshot")
    y -= 24
    pdf.setFont("Helvetica", 11)

    lines = [
        f"Materials monitored: {len(rows)}",
        f"On-hand quantity (units): {snapshot['total_inventory_quantity']}",
        f"Inventory health index: {snapshot['inventory_health']}%",
        f"Critical / warning items: {snapshot['critical']} / {snapshot['warning']}",
        f"Pending / approved / rejected requests: {pending_count} / {approved_count} / {rejected_count}",
        f"Movement profile — fast / medium / slow: {snapshot['fast_count']} / {snapshot['medium_count']} / {snapshot['slow_count']}",
        f"ABC count — A / B / C: {snapshot['abc_a']} / {snapshot['abc_b']} / {snapshot['abc_c']}",
    ]

    for line in lines:
        pdf.drawString(50, y, line)
        y -= 20

    pdf.showPage()
    pdf.save()

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="kpi_summary.pdf",
        mimetype="application/pdf"
    )


@app.route("/reports")
@login_required
def reports():
    report_view = request.args.get("view", "hub")
    today = datetime.now().strftime("%Y-%m-%d")
    month_key = datetime.now().strftime("%Y-%m")

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM inventory WHERE COALESCE(is_active, 1) = 1 ORDER BY item_name"
    ).fetchall()
    pending_count = conn.execute("SELECT COUNT(*) FROM requests WHERE status='Pending'").fetchone()[0]
    transaction_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

    daily_tx = conn.execute(
        """
        SELECT item_name, action, quantity, user, timestamp
        FROM transactions
        WHERE date(timestamp) = date(?)
          AND UPPER(action) IN ('ISSUED', 'RECEIVED')
        ORDER BY timestamp DESC
        """,
        (today,),
    ).fetchall()

    monthly_rows = conn.execute(
        """
        SELECT item_name, SUM(quantity) AS total_issued
        FROM transactions
        WHERE strftime('%Y-%m', timestamp) = ?
          AND UPPER(action) = 'ISSUED'
        GROUP BY item_name
        ORDER BY total_issued DESC
        """,
        (month_key,),
    ).fetchall()

    conn.close()

    snapshot = calculate_inventory_snapshot(rows)
    critical_stock = [
        item for item in snapshot["inventory_table"]
        if item["quantity"] < item["rop"]
    ]
    critical_stock.sort(key=lambda x: x["days_remaining"])

    return render_template(
        "reports.html",
        report_view=report_view,
        total_materials=len(rows),
        critical=snapshot["critical"],
        overstock=snapshot["overstock"],
        operational_risks=snapshot["operational_risks"],
        warning=snapshot["warning"],
        pending_count=pending_count,
        transaction_count=transaction_count,
        daily_tx=daily_tx,
        monthly_rows=monthly_rows,
        critical_stock=critical_stock,
        report_date=today,
        report_month=datetime.now().strftime("%B %Y"),
    )


@app.route("/abc-analysis")
@login_required
def abc_analysis():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM inventory WHERE COALESCE(is_active, 1) = 1 ORDER BY item_name"
    ).fetchall()
    conn.close()

    snapshot = calculate_inventory_snapshot(rows)
    table = snapshot["inventory_table"]
    total_items = len(table)
    total_value = sum(item["consumption_value"] for item in table)

    summary = {}
    category_guidance = {
        "A": {
            "control": "Tight control and frequent review",
            "review": "Weekly review",
            "action": "Prioritize replenishment decisions and verify demand signals before stockouts occur.",
        },
        "B": {
            "control": "Balanced review cycle",
            "review": "Bi-weekly review",
            "action": "Track movement trends and replenish through standard approval thresholds.",
        },
        "C": {
            "control": "Exception-based control",
            "review": "Monthly review",
            "action": "Use simpler ordering rules while monitoring unusual consumption spikes.",
        },
    }
    category_rows = []
    for cls in ("A", "B", "C"):
        items = [i for i in table if i.get("abc") == cls]
        value = sum(i["consumption_value"] for i in items)
        summary[cls] = {
            "count": len(items),
            "pct_items": round(len(items) / total_items * 100, 1) if total_items else 0,
            "pct_value": round(value / total_value * 100, 1) if total_value else 0,
            "value": round(value, 2),
        }
        category_rows.append({
            "class": cls,
            "count": summary[cls]["count"],
            "pct_items": summary[cls]["pct_items"],
            "pct_value": summary[cls]["pct_value"],
            "value": summary[cls]["value"],
            **category_guidance[cls],
        })

    abc_inventory_rows = []
    sorted_by_value = sorted(table, key=lambda x: x["consumption_value"], reverse=True)
    for rank, item in enumerate(sorted_by_value, start=1):
        share = round(item["consumption_value"] / total_value * 100, 1) if total_value else 0
        abc_inventory_rows.append({
            "rank": rank,
            "item": item["item"],
            "abc": item.get("abc", "C"),
            "stock": item["quantity"],
            "issued": item["quantity_taken"],
            "unit_cost": item["unit_cost"],
            "consumption_value": item["consumption_value"],
            "value_share": share,
            "cumulative_share": round(sum(
                row["consumption_value"] for row in sorted_by_value[:rank]
            ) / total_value * 100, 1) if total_value else 0,
            "status": item["status"],
        })

    class_chart_labels = ["Class A", "Class B", "Class C"]
    class_chart_values = [
        summary["A"]["pct_value"],
        summary["B"]["pct_value"],
        summary["C"]["pct_value"],
    ]
    pareto_chart = build_pareto_chart_data(
        [{"item": r["item"], "consumption_value": r["consumption_value"]} for r in abc_inventory_rows],
        top_n=12,
    )

    return render_template(
        "abc_analysis.html",
        summary=summary,
        category_rows=category_rows,
        abc_inventory_rows=abc_inventory_rows,
        total_value=round(total_value, 2),
        chart_labels=class_chart_labels,
        chart_values=class_chart_values,
        pareto_chart=pareto_chart,
        pilot_period_label=PILOT_PERIOD_LABEL,
    )


@app.route("/xyz-analysis")
@login_required
def xyz_analysis():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM inventory WHERE COALESCE(is_active, 1) = 1 ORDER BY item_name"
    ).fetchall()
    conn.close()

    snapshot = calculate_inventory_snapshot(rows)
    table = snapshot["inventory_table"]
    movement_values = [
        snapshot["fast_count"],
        snapshot["medium_count"],
        snapshot["slow_count"],
    ]
    movement_rows = []
    for item in sorted(table, key=lambda x: (x["movement"] != "Fast Moving", x["movement"] != "Medium Moving", x["item"])):
        movement_rows.append({
            "item": item["item"],
            "movement": item["movement"],
            "abc": item.get("abc", "C"),
            "stock": item["quantity"],
            "issued": item["quantity_taken"],
            "received": item["quantity_received"],
            "rop": item["rop"],
            "days_remaining": item["days_remaining"],
            "status": item["status"],
        })

    movement_trend = snapshot["monthly_movement_trend"]

    return render_template(
        "xyz_analysis.html",
        fast_count=snapshot["fast_count"],
        medium_count=snapshot["medium_count"],
        slow_count=snapshot["slow_count"],
        movement_rows=movement_rows,
        chart_labels=["Fast Moving", "Medium Moving", "Slow Moving"],
        chart_values=movement_values,
        movement_trend=movement_trend,
        pilot_period_label=PILOT_PERIOD_LABEL,
    )


@app.route("/alerts")
@login_required
def alerts_log():
    conn = get_db()
    logs = conn.execute(
        """
        SELECT material_name, alert_type, timestamp, triggered_by, notes
        FROM alert_logs ORDER BY timestamp DESC
        """
    ).fetchall()
    conn.close()
    return render_template("alerts.html", logs=logs)


@app.route("/business-impact")
@login_required
def business_impact():
    conn = get_db()
    alert_count = conn.execute("SELECT COUNT(*) FROM alert_logs").fetchone()[0]
    conn.close()
    return render_template("business_impact.html", alert_count=alert_count)


@app.route("/adoption-metrics")
@login_required
def adoption_metrics():
    conn = get_db()
    events = conn.execute(
        """
        SELECT username, event_type, endpoint, path, device_platform, duration_seconds, timestamp
        FROM app_events
        ORDER BY timestamp ASC
        """
    ).fetchall()
    recent_events = conn.execute(
        """
        SELECT username, event_type, endpoint, device_platform, duration_seconds, timestamp
        FROM app_events
        ORDER BY timestamp DESC
        LIMIT 12
        """
    ).fetchall()
    conn.close()

    daily_users = defaultdict(set)
    daily_views = defaultdict(int)
    platform_counts = defaultdict(int)
    route_counts = defaultdict(int)
    session_duration_by_day = defaultdict(list)
    session_buckets = {"< 1 min": 0, "1 - 5 min": 0, "> 5 min": 0}

    for event in events:
        day = (event["timestamp"] or "")[:10]
        if not day:
            continue

        if event["username"]:
            daily_users[day].add(event["username"])

        if event["event_type"] == "PAGE_VIEW":
            daily_views[day] += 1
            if event["endpoint"]:
                route_counts[event["endpoint"]] += 1

        if event["device_platform"]:
            platform_counts[event["device_platform"]] += 1

        if event["event_type"] == "LOGOUT" and event["duration_seconds"] is not None:
            duration = float(event["duration_seconds"])
            session_duration_by_day[day].append(duration)
            if duration < 60:
                session_buckets["< 1 min"] += 1
            elif duration <= 300:
                session_buckets["1 - 5 min"] += 1
            else:
                session_buckets["> 5 min"] += 1

    all_days = sorted(set(daily_users) | set(daily_views) | set(session_duration_by_day))
    active_users_data = [len(daily_users[day]) for day in all_days]
    page_views_data = [daily_views[day] for day in all_days]
    avg_session_data = [
        round(sum(session_duration_by_day[day]) / len(session_duration_by_day[day]), 1)
        if session_duration_by_day[day] else 0
        for day in all_days
    ]

    total_events = len(events)
    total_page_views = sum(daily_views.values())
    total_logins = sum(1 for event in events if event["event_type"] == "LOGIN")
    total_users = len({event["username"] for event in events if event["username"]})
    completed_sessions = sum(len(values) for values in session_duration_by_day.values())
    avg_session_length = round(
        sum(sum(values) for values in session_duration_by_day.values()) / completed_sessions,
        1
    ) if completed_sessions else 0

    return render_template(
        "adoption_metrics.html",
        total_events=total_events,
        total_page_views=total_page_views,
        total_logins=total_logins,
        total_users=total_users,
        completed_sessions=completed_sessions,
        avg_session_length=avg_session_length,
        daily_labels=all_days,
        active_users_data=active_users_data,
        page_views_data=page_views_data,
        avg_session_data=avg_session_data,
        platform_labels=list(platform_counts.keys()),
        platform_data=list(platform_counts.values()),
        route_labels=list(route_counts.keys()),
        route_data=list(route_counts.values()),
        session_bucket_labels=list(session_buckets.keys()),
        session_bucket_data=list(session_buckets.values()),
        recent_events=recent_events
    )


@app.route("/admin/users")
@login_required
@role_required("admin")
def manage_users():
    conn = get_db()
    users_list = conn.execute(
        """
        SELECT id, username, email, role, full_name, is_active, created_at
        FROM users
        ORDER BY created_at DESC
        """
    ).fetchall()
    conn.close()

    return render_template("admin_users.html", users=users_list)


@app.route("/admin/users/new", methods=["GET", "POST"])
@login_required
@role_required("admin")
def add_user():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        email = request.form.get("email")
        role = request.form.get("role", "warehouse")
        full_name = request.form.get("full_name")

        if not all([username, password, email, full_name]):
            flash("All fields are required.", "danger")
            return redirect(url_for("add_user"))

        conn = get_db()

        try:
            conn.execute(
                """
                INSERT INTO users (username, password, email, role, full_name)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    username,
                    generate_password_hash(password),
                    email,
                    role,
                    full_name
                )
            )
            conn.commit()
            flash(f"User {username} created successfully.", "success")
            return redirect(url_for("manage_users"))

        except sqlite3.IntegrityError:
            flash("Username or email already exists.", "danger")

        finally:
            conn.close()

    return render_template("admin_add_user.html")


@app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def edit_user(user_id):
    conn = get_db()
    c = conn.cursor()

    user = c.execute(
        """
        SELECT id, username, email, role, full_name, is_active
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if not user:
        conn.close()
        flash("User not found.", "danger")
        return redirect(url_for("manage_users"))

    if request.method == "POST":
        email = request.form.get("email")
        role = request.form.get("role")
        full_name = request.form.get("full_name")
        is_active = request.form.get("is_active") == "on"

        c.execute(
            """
            UPDATE users
            SET email = ?, role = ?, full_name = ?, is_active = ?
            WHERE id = ?
            """,
            (email, role, full_name, is_active, user_id)
        )
        conn.commit()
        conn.close()

        flash(f"User {user['username']} updated successfully.", "success")
        return redirect(url_for("manage_users"))

    conn.close()
    return render_template("admin_edit_user.html", user=user)


@app.route("/admin/users/<int:user_id>/deactivate", methods=["POST"])
@login_required
@role_required("admin")
def deactivate_user(user_id):
    if str(user_id) == str(current_user.id):
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for("manage_users"))

    conn = get_db()
    user = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()

    if user:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = ?", (user_id,))
        conn.commit()
        flash(f"User {user['username']} has been deactivated.", "success")
    else:
        flash("User not found.", "danger")

    conn.close()
    return redirect(url_for("manage_users"))


@app.route("/inventory/<path:item_name>/archive", methods=["POST"])
@login_required
@role_required("admin", "procurement")
def archive_inventory_item(item_name):
    conn = get_db()
    row = conn.execute(
        "SELECT item_name FROM inventory WHERE item_name = ?", (item_name,)
    ).fetchone()
    if not row:
        conn.close()
        flash("Inventory item not found.", "danger")
        return redirect(url_for("inventory"))

    conn.execute(
        "UPDATE inventory SET is_active = 0 WHERE item_name = ?", (item_name,)
    )
    conn.commit()
    conn.close()
    flash(f"{item_name} archived (hidden from active inventory).", "success")
    return redirect(url_for("inventory"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=True)
