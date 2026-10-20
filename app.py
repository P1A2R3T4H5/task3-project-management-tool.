from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, join_room, emit
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = "replace-this-before-deployment"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///taskflow.db"
db = SQLAlchemy(app)
login = LoginManager(app)
login.login_view = "login"
socketio = SocketIO(app, cors_allowed_origins="*")
members = db.Table("members", db.Column("user_id", db.Integer, db.ForeignKey("user.id")), db.Column("project_id", db.Integer, db.ForeignKey("project.id")))

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default="")
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    team = db.relationship("User", secondary=members, backref="joined_projects")
    tasks = db.relationship("Task", backref="project", cascade="all, delete-orphan")

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(20), default="To Do")
    priority = db.Column(db.String(20), default="Medium")
    due_date = db.Column(db.String(20), default="")
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    assignee_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    assignee = db.relationship("User", foreign_keys=[assignee_id])
    comments = db.relationship("Comment", backref="task", cascade="all, delete-orphan")

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    author = db.relationship("User")

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login.user_loader
def load_user(uid): return db.session.get(User, int(uid))

def allowed(project):
    return current_user.is_authenticated and (project.owner_id == current_user.id or current_user in project.team)

def get_project(pid):
    p = db.session.get(Project, pid)
    if not p or not allowed(p):
        flash("Project not found or access denied.", "error")
        return None
    return p

def notify(uid, message, pid=None):
    db.session.add(Notification(user_id=uid, message=message))
    db.session.commit()
    socketio.emit("notification", {"message": message}, room=f"user_{uid}")
    if pid: socketio.emit("project_update", {"message": message}, room=f"project_{pid}")

@socketio.on("join")
def join(data):
    if current_user.is_authenticated:
        join_room(f"user_{current_user.id}")
        pid = data.get("project_id")
        if pid:
            p = db.session.get(Project, int(pid))
            if p and allowed(p): join_room(f"project_{pid}")

@app.route("/")
def home():
    return redirect(url_for("dashboard")) if current_user.is_authenticated else render_template("home.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name, email, password = request.form["name"].strip(), request.form["email"].strip().lower(), request.form["password"]
        if len(password) < 6: flash("Password must contain at least 6 characters.", "error")
        elif User.query.filter_by(email=email).first(): flash("Email is already registered.", "error")
        else:
            u = User(name=name, email=email, password=generate_password_hash(password))
            db.session.add(u); db.session.commit(); login_user(u)
            return redirect(url_for("dashboard"))
    return render_template("auth.html", mode="Register")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(email=request.form["email"].strip().lower()).first()
        if u and check_password_hash(u.password, request.form["password"]):
            login_user(u); return redirect(url_for("dashboard"))
        flash("Incorrect email or password.", "error")
    return render_template("auth.html", mode="Login")

@app.route("/logout")
@login_required
def logout():
    logout_user(); return redirect(url_for("home"))

@app.route("/dashboard")
@login_required
def dashboard():
    projects = Project.query.filter(db.or_(Project.owner_id == current_user.id, Project.team.any(id=current_user.id))).all()
    notes = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(10).all()
    return render_template("dashboard.html", projects=projects, notes=notes)

@app.route("/projects", methods=["POST"])
@login_required
def create_project():
    name = request.form["name"].strip()
    if not name: flash("Project name is required.", "error"); return redirect(url_for("dashboard"))
    p = Project(name=name, description=request.form.get("description","").strip(), owner_id=current_user.id)
    p.team.append(current_user); db.session.add(p); db.session.commit()
    return redirect(url_for("project", pid=p.id))

@app.route("/projects/<int:pid>")
@login_required
def project(pid):
    p = get_project(pid)
    if not p: return redirect(url_for("dashboard"))
    team = list(p.team)
    owner = db.session.get(User, p.owner_id)
    if owner and owner not in team: team.append(owner)
    return render_template("project.html", p=p, team=team)

@app.route("/projects/<int:pid>/members", methods=["POST"])
@login_required
def add_member(pid):
    p = get_project(pid)
    if not p: return redirect(url_for("dashboard"))
    if p.owner_id != current_user.id: flash("Only the owner can invite members.", "error")
    else:
        u = User.query.filter_by(email=request.form["email"].strip().lower()).first()
        if not u: flash("User must register first.", "error")
        elif u in p.team: flash("Already a member.", "error")
        else:
            p.team.append(u); db.session.commit(); notify(u.id, f"Added to project: {p.name}", p.id); flash("Member added.", "success")
    return redirect(url_for("project", pid=pid))

@app.route("/projects/<int:pid>/tasks", methods=["POST"])
@login_required
def add_task(pid):
    p = get_project(pid)
    if not p: return redirect(url_for("dashboard"))
    aid = request.form.get("assignee_id") or None
    if aid and int(aid) not in [u.id for u in p.team] and int(aid) != p.owner_id: aid = None
    t = Task(title=request.form["title"].strip(), description=request.form.get("description","").strip(),
             status=request.form.get("status","To Do"), priority=request.form.get("priority","Medium"),
             due_date=request.form.get("due_date",""), project_id=pid, assignee_id=aid)
    if not t.title: flash("Task title is required.", "error")
    else:
        db.session.add(t); db.session.commit()
        if aid: notify(int(aid), f"Assigned task: {t.title}", pid)
        socketio.emit("project_update", {"message": f"New task: {t.title}"}, room=f"project_{pid}")
    return redirect(url_for("project", pid=pid))

@app.route("/tasks/<int:tid>/update", methods=["POST"])
@login_required
def update_task(tid):
    t = db.session.get(Task, tid)
    if not t or not allowed(t.project): flash("Access denied.", "error"); return redirect(url_for("dashboard"))
    t.status = request.form.get("status", t.status); t.priority = request.form.get("priority", t.priority)
    t.due_date = request.form.get("due_date", t.due_date)
    aid = request.form.get("assignee_id") or None
    t.assignee_id = int(aid) if aid and (int(aid) == t.project.owner_id or int(aid) in [u.id for u in t.project.team]) else None
    db.session.commit()
    if t.assignee_id: notify(t.assignee_id, f"Task assigned to you: {t.title}", t.project_id)
    socketio.emit("project_update", {"message": f"Updated task: {t.title}"}, room=f"project_{t.project_id}")
    return redirect(url_for("project", pid=t.project_id))

@app.route("/tasks/<int:tid>/comments", methods=["POST"])
@login_required
def comment(tid):
    t = db.session.get(Task, tid)
    if not t or not allowed(t.project): flash("Access denied.", "error"); return redirect(url_for("dashboard"))
    body = request.form["body"].strip()
    if body:
        db.session.add(Comment(body=body, task_id=tid, user_id=current_user.id)); db.session.commit()
        socketio.emit("project_update", {"message": f"New comment on: {t.title}"}, room=f"project_{t.project_id}")
    return redirect(url_for("project", pid=t.project_id) + f"#task-{tid}")

with app.app_context(): db.create_all()
if __name__ == "__main__": socketio.run(app, debug=True)
