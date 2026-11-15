
import streamlit as st
import sqlite3, hashlib, secrets, hmac, io, csv
from datetime import date, datetime
import pandas as pd

DB_PATH = "crm_data.db"
MAX_USERS = 9

st.set_page_config(page_title="Call CRM", page_icon="📞", layout="wide")

def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def pw_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return salt + "$" + digest

def pw_ok(password, stored):
    try:
        salt, digest = stored.split("$", 1)
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
        return hmac.compare_digest(check, digest)
    except Exception:
        return False

def init_db():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, full_name TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'user', active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS leads(
          id INTEGER PRIMARY KEY AUTOINCREMENT, client_name TEXT NOT NULL,
          phone TEXT, email TEXT, district TEXT, state TEXT,
          proposal_sent TEXT, status TEXT DEFAULT 'New', priority TEXT DEFAULT 'Normal',
          feedback TEXT, followup_date TEXT, assigned_to INTEGER,
          source TEXT DEFAULT 'Imported', created_at TEXT, updated_at TEXT,
          extra_notes TEXT,
          FOREIGN KEY(assigned_to) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS call_logs(
          id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER NOT NULL,
          user_id INTEGER NOT NULL, call_date TEXT NOT NULL, outcome TEXT,
          feedback TEXT, next_followup TEXT, email_sent TEXT DEFAULT 'No',
          email_notes TEXT, created_at TEXT,
          FOREIGN KEY(lead_id) REFERENCES leads(id),
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_leads_followup ON leads(followup_date);
        CREATE INDEX IF NOT EXISTS idx_leads_assigned ON leads(assigned_to);
        """)
        count = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        if count == 0:
            c.execute("INSERT INTO users(username,password_hash,full_name,role) VALUES(?,?,?,?)",
                      ("admin", pw_hash("admin123"), "CRM Administrator", "admin"))

def current_user():
    return st.session_state.get("user")

def login_screen():
    st.title("📞 Call CRM")
    st.caption("Lead management • Call feedback • Follow-up tracking")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        ok = st.form_submit_button("Log in", use_container_width=True)
    if ok:
        with conn() as c:
            u = c.execute("SELECT * FROM users WHERE username=? AND active=1", (username.strip(),)).fetchone()
        if u and pw_ok(password, u["password_hash"]):
            st.session_state.user = dict(u)
            st.rerun()
        else:
            st.error("Incorrect username or password, or this account is inactive.")
    st.info("First login: username **admin**, password **admin123**. Change this password immediately in User Management.")

def query_df(sql, params=()):
    with conn() as c:
        return pd.read_sql_query(sql, c, params=params)

def user_filter(u):
    if u["role"] == "admin":
        return "", ()
    return " WHERE l.assigned_to=?", (u["id"],)

def safe_str(v):
    if pd.isna(v): return ""
    if isinstance(v, float) and v.is_integer(): return str(int(v))
    return str(v).strip()

def import_file(upload, assign_id):
    if upload.name.lower().endswith(".csv"):
        frame = pd.read_csv(upload, dtype=str, keep_default_na=False)
    else:
        frame = pd.read_excel(upload, dtype=str).fillna("")
    frame.columns = [str(x).strip() for x in frame.columns]
    aliases = {
        "client_name": ["Client Name","Name","Lead Name","School Name","Customer Name"],
        "phone": ["Contact No","Contact Number","Phone","Mobile","Mobile Number"],
        "email": ["Email","Email ID","E-mail","Email Address"],
        "district": ["Distt.","District","City"],
        "state": ["State"],
        "proposal_sent": ["Proposal Send","Proposal Sent"],
        "feedback": ["Remark","Remarks","Feedback","Notes"],
    }
    lower = {str(col).strip().lower(): col for col in frame.columns}
    def find_col(key):
        for alias in aliases[key]:
            if alias.lower() in lower: return lower[alias.lower()]
        return None
    mapped = {k: find_col(k) for k in aliases}
    if not mapped["client_name"]:
        raise ValueError("Could not find a Client Name column. Please include a 'Client Name' header.")
    extra_cols = [col for col in frame.columns if col not in [v for v in mapped.values() if v]]
    inserted = 0
    with conn() as c:
        for _, r in frame.iterrows():
            name = safe_str(r[mapped["client_name"]])
            if not name: continue
            vals = {k: safe_str(r[v]) if v else "" for k,v in mapped.items()}
            extras = " | ".join(f"{col}: {safe_str(r[col])}" for col in extra_cols if safe_str(r[col]))
            c.execute("""INSERT INTO leads(client_name,phone,email,district,state,proposal_sent,
                      feedback,assigned_to,source,created_at,updated_at,extra_notes)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (name, vals["phone"], vals["email"], vals["district"], vals["state"],
                       vals["proposal_sent"], vals["feedback"], assign_id, "Import",
                       datetime.now().isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"), extras))
            inserted += 1
    return inserted

def status_colour(followup):
    if not followup: return "⚪"
    try:
        d = date.fromisoformat(followup)
    except Exception:
        return "⚪"
    if d < date.today(): return "🔴"
    if d == date.today(): return "🟠"
    return "🟢"

def main_app():
    u = current_user()
    with st.sidebar:
        st.markdown("### Call CRM")
        st.write(f"Signed in: **{u['full_name']}**")
        st.caption(f"Role: {u['role'].title()}")
        page = st.radio("Navigation", ["Dashboard","Leads","Add Lead","Import / Export","User Management"] if u["role"]=="admin" else ["Dashboard","Leads","Add Lead","Import / Export"])
        if st.button("Log out", use_container_width=True):
            st.session_state.pop("user", None)
            st.rerun()

    if page == "Dashboard":
        st.title("Dashboard")
        where, params = user_filter(u)
        leads = query_df("SELECT l.* FROM leads l"+where, params)
        today = date.today().isoformat()
        total = len(leads)
        overdue = int(((leads.followup_date.fillna("") != "") & (leads.followup_date.fillna("") < today)).sum()) if total else 0
        due = int((leads.followup_date.fillna("") == today).sum()) if total else 0
        scheduled = int((leads.followup_date.fillna("") > today).sum()) if total else 0
        c1,c2,c3,c4 = st.columns(4)
        c1.metric("Total leads", total)
        c2.metric("Overdue follow-ups", overdue)
        c3.metric("Due today", due)
        c4.metric("Upcoming", scheduled)
        st.subheader("Follow-ups requiring attention")
        attention = leads[leads.followup_date.fillna("").apply(lambda x: bool(x) and x <= today)].copy() if total else leads
        if not attention.empty:
            attention["Follow-up"] = attention.followup_date.apply(lambda x: status_colour(x))
            st.dataframe(attention[["Follow-up","client_name","phone","district","state","status","followup_date","assigned_to"]].sort_values("followup_date"),
                         use_container_width=True, hide_index=True)
        else:
            st.success("No overdue or due-today follow-ups.")
        st.subheader("Lead status")
        if total:
            st.bar_chart(leads.status.fillna("New").value_counts())
        if u["role"] == "admin":
            st.subheader("User-wise activity")
            activity = query_df("""SELECT u.full_name, COUNT(cl.id) AS calls_made
                FROM users u LEFT JOIN call_logs cl ON cl.user_id=u.id
                WHERE u.active=1 GROUP BY u.id ORDER BY calls_made DESC""")
            st.dataframe(activity, use_container_width=True, hide_index=True)

    elif page == "Leads":
        st.title("Leads & Call Records")
        where, params = user_filter(u)
        leads = query_df("SELECT l.*,u.full_name assigned_name FROM leads l LEFT JOIN users u ON u.id=l.assigned_to"+where+" ORDER BY l.id DESC", params)
        a,b,c = st.columns([2,1,1])
        search = a.text_input("Search name, phone, district or email")
        filter_status = b.selectbox("Status", ["All","New","Contacted","Interested","Meeting Scheduled","Proposal Sent","Won","Lost","Not Interested"])
        show = c.selectbox("Follow-up", ["All","Overdue","Due today","Upcoming","No date"])
        if search:
            mask = leads.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
            leads = leads[mask]
        if filter_status != "All": leads = leads[leads.status == filter_status]
        today = date.today().isoformat()
        if show == "Overdue": leads = leads[(leads.followup_date.fillna("") != "") & (leads.followup_date.fillna("") < today)]
        elif show == "Due today": leads = leads[leads.followup_date.fillna("") == today]
        elif show == "Upcoming": leads = leads[leads.followup_date.fillna("") > today]
        elif show == "No date": leads = leads[leads.followup_date.fillna("") == ""]
        if leads.empty:
            st.info("No leads match these filters.")
        else:
            leads["Alert"] = leads.followup_date.apply(status_colour)
            st.dataframe(leads[["id","Alert","client_name","phone","email","district","state","status","priority","followup_date","assigned_name"]].rename(columns={"id":"ID","client_name":"Client","phone":"Phone","email":"Email","district":"District","state":"State","status":"Status","priority":"Priority","followup_date":"Follow-up","assigned_name":"Assigned to"}),
                         use_container_width=True, hide_index=True)
            st.caption("🔴 Overdue   🟠 Due today   🟢 Upcoming   ⚪ No follow-up date")
        st.divider()
        st.subheader("Open a lead")
        lead_ids = leads.id.tolist()
        if lead_ids:
            selected = st.selectbox("Select lead ID", lead_ids, format_func=lambda x: f"#{x} — {leads.loc[leads.id==x,'client_name'].iloc[0]}")
            lead_detail(selected, u)

    elif page == "Add Lead":
        st.title("Add a new lead")
        with st.form("add_lead", clear_on_submit=True):
            x1,x2 = st.columns(2)
            name = x1.text_input("Client / School name *")
            phone = x2.text_input("Contact number")
            email = x1.text_input("Email address")
            district = x2.text_input("District / City")
            state = x1.text_input("State")
            proposal = x2.selectbox("Proposal sent?", ["No","Yes","Pending"])
            status = x1.selectbox("Lead status", ["New","Contacted","Interested","Meeting Scheduled","Proposal Sent","Won","Lost","Not Interested"])
            priority = x2.selectbox("Priority", ["Normal","High","Low"])
            feedback = st.text_area("Initial feedback / context")
            follow = st.date_input("Next follow-up date", value=None)
            if u["role"] == "admin":
                users = query_df("SELECT id,full_name FROM users WHERE active=1 ORDER BY full_name")
                assignee = st.selectbox("Assign to", users.id.tolist(), format_func=lambda i: users.loc[users.id==i,"full_name"].iloc[0]) if not users.empty else u["id"]
            else:
                assignee = u["id"]
            save = st.form_submit_button("Save lead", use_container_width=True)
        if save:
            if not name.strip():
                st.error("Client / School name is required.")
            else:
                now = datetime.now().isoformat(timespec="seconds")
                with conn() as db:
                    db.execute("""INSERT INTO leads(client_name,phone,email,district,state,proposal_sent,status,
                    priority,feedback,followup_date,assigned_to,source,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (name.strip(),phone.strip(),email.strip(),district.strip(),state.strip(),proposal,status,
                     priority,feedback,follow.isoformat() if follow else None,assignee,"Manual",now,now))
                st.success("Lead saved.")

    elif page == "Import / Export":
        st.title("Import / Export")
        st.write("Upload your lead list in CSV or Excel (.xlsx). Existing rows are retained; imports add new leads.")
        st.info("Your uploaded workbook has columns for Client Name, Contact No, Distt., State, Proposal Send and Remark. Additional unnamed columns will be preserved as extra notes.")
        upload = st.file_uploader("Choose CSV or Excel file", type=["csv","xlsx"])
        if u["role"] == "admin":
            users = query_df("SELECT id,full_name FROM users WHERE active=1 ORDER BY full_name")
            assignee = st.selectbox("Assign imported leads to", users.id.tolist(), format_func=lambda i: users.loc[users.id==i,"full_name"].iloc[0]) if not users.empty else u["id"]
        else:
            assignee = u["id"]
        if st.button("Import leads", disabled=upload is None):
            try:
                n = import_file(upload, assignee)
                st.success(f"Imported {n} leads.")
            except Exception as e:
                st.error(f"Import failed: {e}")
        where, params = user_filter(u)
        export_df = query_df("SELECT l.client_name AS 'Client Name',l.phone AS 'Contact No',l.email AS Email,l.district AS District,l.state AS State,l.proposal_sent AS 'Proposal Sent',l.status AS Status,l.priority AS Priority,l.feedback AS Feedback,l.followup_date AS 'Follow-up Date',u.full_name AS 'Assigned To',l.extra_notes AS 'Imported Extra Notes' FROM leads l LEFT JOIN users u ON u.id=l.assigned_to"+where, params)
        st.download_button("Download leads as CSV", export_df.to_csv(index=False).encode("utf-8-sig"), "crm_leads_export.csv", "text/csv")
        st.caption("Call history can be viewed by opening an individual lead.")

    elif page == "User Management" and u["role"] == "admin":
        st.title("User Management")
        users = query_df("SELECT id,username,full_name,role,active FROM users ORDER BY id")
        st.dataframe(users, use_container_width=True, hide_index=True)
        st.caption(f"Maximum {MAX_USERS} accounts including the administrator.")
        with st.expander("Create a user"):
            with st.form("create_user"):
                uname = st.text_input("Username")
                full = st.text_input("Full name")
                p1 = st.text_input("Temporary password", type="password")
                role = st.selectbox("Role", ["user","admin"])
                create = st.form_submit_button("Create user")
            if create:
                if not uname.strip() or not full.strip() or len(p1)<8:
                    st.error("Enter username, full name and a password of at least 8 characters.")
                elif len(users) >= MAX_USERS:
                    st.error("The 9-account limit has been reached.")
                else:
                    try:
                        with conn() as db:
                            db.execute("INSERT INTO users(username,password_hash,full_name,role) VALUES(?,?,?,?)",
                                       (uname.strip(),pw_hash(p1),full.strip(),role))
                        st.success("User created. They can now log in.")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("That username already exists.")
        with st.expander("Reset a user's password / activate account"):
            with st.form("manage_user"):
                active_users = query_df("SELECT id,username,full_name,active FROM users ORDER BY id")
                uid = st.selectbox("Choose account", active_users.id.tolist(), format_func=lambda i: active_users.loc[active_users.id==i,"username"].iloc[0])
                newpw = st.text_input("New password (leave blank to keep current)", type="password")
                active = st.checkbox("Account active", value=True)
                update = st.form_submit_button("Update account")
            if update:
                with conn() as db:
                    if newpw:
                        if len(newpw)<8: st.error("Password must be at least 8 characters.")
                        else: db.execute("UPDATE users SET password_hash=?,active=? WHERE id=?", (pw_hash(newpw),int(active),uid))
                    else:
                        db.execute("UPDATE users SET active=? WHERE id=?", (int(active),uid))
                st.success("Account updated.")
                st.rerun()

def lead_detail(lead_id, u):
    with conn() as db:
        lead = db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead: return
    if u["role"] != "admin" and lead["assigned_to"] != u["id"]:
        st.error("You do not have access to this lead.")
        return
    st.markdown(f"### {lead['client_name']}  {status_colour(lead['followup_date'])}")
    st.write(f"**Phone:** {lead['phone'] or '—'}  |  **Email:** {lead['email'] or '—'}")
    st.write(f"**Location:** {lead['district'] or '—'}, {lead['state'] or '—'}")
    if lead["extra_notes"]: st.caption("Imported additional fields: " + lead["extra_notes"])
    st.subheader("Update lead")
    with st.form(f"edit_{lead_id}"):
        x1,x2 = st.columns(2)
        email = x1.text_input("Email", value=lead["email"] or "")
        phone = x2.text_input("Phone", value=lead["phone"] or "")
        status_options = ["New","Contacted","Interested","Meeting Scheduled","Proposal Sent","Won","Lost","Not Interested"]
        status = x1.selectbox("Status", status_options, index=status_options.index(lead["status"]) if lead["status"] in status_options else 0)
        priority_options = ["Normal","High","Low"]
        priority = x2.selectbox("Priority", priority_options, index=priority_options.index(lead["priority"]) if lead["priority"] in priority_options else 0)
        feedback = st.text_area("Current summary / feedback", value=lead["feedback"] or "")
        fdate = st.date_input("Next follow-up date", value=date.fromisoformat(lead["followup_date"]) if lead["followup_date"] else None)
        save = st.form_submit_button("Save changes")
    if save:
        with conn() as db:
            db.execute("""UPDATE leads SET email=?,phone=?,status=?,priority=?,feedback=?,followup_date=?,updated_at=? WHERE id=?""",
                       (email,phone,status,priority,feedback,fdate.isoformat() if fdate else None,datetime.now().isoformat(timespec="seconds"),lead_id))
        st.success("Lead updated.")
        st.rerun()
    st.subheader("Log a call / email")
    with st.form(f"log_{lead_id}", clear_on_submit=True):
        call_date = st.date_input("Activity date", value=date.today())
        outcome = st.selectbox("Call outcome", ["Connected","No answer","Switched off","Busy","Meeting scheduled","Interested","Not interested","Callback requested","Other"])
        notes = st.text_area("Call feedback / discussion notes")
        next_date = st.date_input("Next follow-up date (optional)", value=None, key=f"next_{lead_id}")
        email_sent = st.selectbox("Email sent?", ["No","Yes"])
        email_notes = st.text_area("Email subject / notes (optional)")
        log = st.form_submit_button("Save activity")
    if log:
        with conn() as db:
            db.execute("""INSERT INTO call_logs(lead_id,user_id,call_date,outcome,feedback,next_followup,email_sent,email_notes,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (lead_id,u["id"],call_date.isoformat(),outcome,notes,next_date.isoformat() if next_date else None,email_sent,email_notes,datetime.now().isoformat(timespec="seconds")))
            db.execute("""UPDATE leads SET feedback=?,followup_date=?,status=?,updated_at=? WHERE id=?""",
                       (notes or lead["feedback"],next_date.isoformat() if next_date else lead["followup_date"],
                        "Contacted" if outcome=="Connected" and lead["status"]=="New" else lead["status"],
                        datetime.now().isoformat(timespec="seconds"),lead_id))
        st.success("Activity recorded.")
        st.rerun()
    st.subheader("Activity history")
    logs = query_df("""SELECT cl.call_date,cl.outcome,cl.feedback,cl.next_followup,cl.email_sent,cl.email_notes,u.full_name
        FROM call_logs cl JOIN users u ON u.id=cl.user_id WHERE cl.lead_id=? ORDER BY cl.id DESC""", (lead_id,))
    if logs.empty: st.info("No calls or emails logged yet.")
    else: st.dataframe(logs.rename(columns={"call_date":"Date","outcome":"Outcome","feedback":"Feedback","next_followup":"Next follow-up","email_sent":"Email sent","email_notes":"Email notes","full_name":"Logged by"}), use_container_width=True, hide_index=True)

init_db()
if not current_user():
    login_screen()
else:
    main_app()
