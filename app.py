import os
import io
import csv
import json
import secrets
import string
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from openpyxl import load_workbook
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
import qrcode

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-this-secret-key"),
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///railway_id_cards.db").replace("postgres://", "postgresql://", 1),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
)
os.makedirs(app.instance_path, exist_ok=True)
db = SQLAlchemy(app)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="department")
    department = db.Column(db.String(160), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hrms_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    pf_no = db.Column(db.String(40), default="")
    name = db.Column(db.String(180), default="")
    designation = db.Column(db.String(240), default="")
    department = db.Column(db.String(160), default="")
    railway_unit = db.Column(db.String(100), default="")
    source_updated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class CardRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_ref = db.Column(db.String(24), unique=True, nullable=False, index=True)
    hrms_id = db.Column(db.String(20), nullable=False, index=True)
    name = db.Column(db.String(180), nullable=False)
    designation = db.Column(db.String(240), nullable=False)
    department = db.Column(db.String(160), nullable=False)
    pf_no = db.Column(db.String(40), default="")
    station = db.Column(db.String(100), nullable=False)
    mobile = db.Column(db.String(20), nullable=False)
    photo_data = db.Column(db.LargeBinary, nullable=False)
    photo_mime = db.Column(db.String(40), default="image/jpeg")
    employee_signature_data = db.Column(db.LargeBinary, nullable=True)
    correction_made = db.Column(db.Boolean, default=False, nullable=False)
    requested_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    status = db.Column(db.String(30), default="Submitted", nullable=False)
    requested_by = db.relationship("User", backref="card_requests")


class PortalSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(80), unique=True, nullable=False)
    setting_value = db.Column(db.String(240), nullable=False, default="")


class StoredAsset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_key = db.Column(db.String(40), unique=True, nullable=False)
    filename = db.Column(db.String(240), nullable=False)
    mime_type = db.Column(db.String(80), nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


ASSET_OPTIONS = {
    "reference_sample": "Reference ID Card Sample",
    "front_template": "Blank Front Template",
    "back_template": "Blank Back Template",
    "railway_logo": "Railway / Ashoka Logo",
    "division_logo": "Vadodara Division Logo",
    "authority_signature": "Issuing Authority Signature",
}


def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if uid else None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user or not user.is_active:
            session.clear()
            flash("कृपया पहले लॉगिन करें।", "warning")
            return redirect(url_for("login"))
        if user.must_change_password and request.endpoint != "change_password":
            return redirect(url_for("change_password"))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user().role != "admin":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def department_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user().role != "department":
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(24)
    return session["csrf_token"]


@app.before_request
def protect_post_requests():
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
            abort(400, "Security token expired. Please refresh the page and try again.")


@app.context_processor
def inject_globals():
    return {"current_user": current_user(), "csrf_token": csrf_token, "asset_options": ASSET_OPTIONS}


def seed_admin():
    if not User.query.filter_by(role="admin").first():
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD", "Brc@2026!")
        admin = User(username=username, role="admin", must_change_password=True)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()


with app.app_context():
    db.create_all()
    # Lightweight additive migration for databases created by earlier portal versions.
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    card_columns = {column["name"] for column in inspector.get_columns("card_request")}
    if "employee_signature_data" not in card_columns:
        with db.engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE card_request ADD COLUMN employee_signature_data BYTEA" if db.engine.dialect.name == "postgresql" else "ALTER TABLE card_request ADD COLUMN employee_signature_data BLOB")
    seed_admin()


@app.route("/")
def index():
    if current_user():
        return redirect(url_for("admin_dashboard" if current_user().role == "admin" else "department_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            session.clear()
            session["user_id"] = user.id
            session["csrf_token"] = secrets.token_urlsafe(24)
            session.permanent = True
            if user.must_change_password:
                return redirect(url_for("change_password"))
            return redirect(url_for("admin_dashboard" if user.role == "admin" else "department_dashboard"))
        flash("Login ID या Password सही नहीं है, अथवा अकाउंट निष्क्रिय है।", "danger")
    return render_template("login.html")


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    user = current_user()
    if request.method == "POST":
        old = request.form.get("old_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not user.check_password(old):
            flash("वर्तमान पासवर्ड सही नहीं है।", "danger")
        elif len(new) < 10:
            flash("नया पासवर्ड कम से कम 10 अक्षरों का होना चाहिए।", "warning")
        elif new != confirm:
            flash("नया पासवर्ड और पुष्टि पासवर्ड मेल नहीं खाते।", "danger")
        else:
            user.set_password(new)
            user.must_change_password = False
            db.session.commit()
            flash("पासवर्ड सफलतापूर्वक बदल दिया गया है।", "success")
            return redirect(url_for("admin_dashboard" if user.role == "admin" else "department_dashboard"))
    return render_template("change_password.html")


@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("आप सफलतापूर्वक लॉगआउट हो गए हैं।", "success")
    return redirect(url_for("login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    total_employees = Employee.query.count()
    total_departments = db.session.query(Employee.department).filter(Employee.department != "").distinct().count()
    total_users = User.query.filter_by(role="department").count()
    total_cards = CardRequest.query.count()
    recent = CardRequest.query.order_by(CardRequest.created_at.desc()).limit(8).all()
    return render_template("admin_dashboard.html", total_employees=total_employees,
                           total_departments=total_departments, total_users=total_users,
                           total_cards=total_cards, recent=recent)


def normalize_header(value):
    return " ".join(str(value or "").replace("\n", " ").strip().lower().split())


def clean_cell(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def import_hrms_workbook(file_storage):
    workbook = load_workbook(file_storage, read_only=True, data_only=True)
    sheet = workbook[workbook.sheetnames[0]]
    header_row = None
    headers = []
    for idx, row in enumerate(sheet.iter_rows(min_row=1, max_row=12, values_only=True), start=1):
        values = [normalize_header(v) for v in row]
        if "hrms id" in values and "name" in values:
            header_row, headers = idx, values
            break
    if not header_row:
        raise ValueError("HRMS ID और Name वाले header नहीं मिले। कृपया HRMS Excel की सही फाइल अपलोड करें।")

    aliases = {
        "hrms_id": ["hrms id", "hrmsid"],
        "name": ["name", "employee name"],
        "designation": ["designation", "design."],
        "department": ["department", "dept", "department name"],
        "pf_no": ["ipas id", "pf no", "pf number", "provident fund no"],
        "railway_unit": ["railway unit", "unit"],
    }
    positions = {}
    for key, options in aliases.items():
        for opt in options:
            if opt in headers:
                positions[key] = headers.index(opt)
                break
    required = [key for key in ("hrms_id", "name", "designation", "department") if key not in positions]
    if required:
        raise ValueError("अनिवार्य कॉलम नहीं मिले: " + ", ".join(required))

    inserted = updated = skipped = 0
    for row in sheet.iter_rows(min_row=header_row + 1, values_only=True):
        def val(key):
            pos = positions.get(key)
            return clean_cell(row[pos]) if pos is not None and pos < len(row) else ""
        hrms_id = val("hrms_id").upper().replace(" ", "")
        if not hrms_id or not val("name"):
            skipped += 1
            continue
        emp = Employee.query.filter_by(hrms_id=hrms_id).first()
        if not emp:
            emp = Employee(hrms_id=hrms_id)
            db.session.add(emp)
            inserted += 1
        else:
            updated += 1
        emp.name = val("name")
        emp.designation = val("designation")
        emp.department = val("department")
        emp.pf_no = val("pf_no")
        emp.railway_unit = val("railway_unit")
        emp.source_updated_at = datetime.utcnow()
    db.session.commit()
    workbook.close()
    return inserted, updated, skipped


@app.route("/admin/hrms-upload", methods=["GET", "POST"])
@admin_required
def hrms_upload():
    if request.method == "POST":
        uploaded = request.files.get("hrms_file")
        if not uploaded or not uploaded.filename:
            flash("कृपया HRMS Excel फाइल चुनें।", "warning")
        elif uploaded.filename.lower().endswith(".xls") and not uploaded.filename.lower().endswith((".xlsx", ".xlsm")):
            flash("पुरानी .xls फाइल सीधे स्वीकार नहीं होगी। इसे Excel में खोलकर .xlsx के रूप में Save करें।", "danger")
        else:
            try:
                inserted, updated, skipped = import_hrms_workbook(uploaded)
                flash(f"HRMS import पूरा: {inserted} नए, {updated} अपडेट, {skipped} रिक्त/छोड़े गए रिकॉर्ड।", "success")
                return redirect(url_for("admin_dashboard"))
            except Exception as exc:
                db.session.rollback()
                flash(f"Import नहीं हो सका: {exc}", "danger")
    return render_template("hrms_upload.html", employee_count=Employee.query.count())


@app.route("/admin/departments", methods=["GET", "POST"])
@admin_required
def departments():
    department_names = [r[0] for r in db.session.query(Employee.department).filter(Employee.department != "").distinct().order_by(Employee.department).all()]
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        department = request.form.get("department", "").strip()
        password = request.form.get("password", "")
        if not username or not department or len(password) < 10:
            flash("सभी जानकारी भरें। पासवर्ड कम से कम 10 अक्षरों का होना चाहिए।", "warning")
        elif User.query.filter_by(username=username).first():
            flash("यह Login ID पहले से मौजूद है।", "danger")
        else:
            user = User(username=username, role="department", department=department)
            user.set_password(password)
            user.must_change_password = True
            db.session.add(user)
            db.session.commit()
            flash(f"{department} का Login ID सफलतापूर्वक बनाया गया। पहले लॉगिन पर पासवर्ड बदलना होगा।", "success")
            return redirect(url_for("departments"))
    users = User.query.filter_by(role="department").order_by(User.department, User.username).all()
    return render_template("departments.html", users=users, department_names=department_names)


@app.route("/admin/user/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id):
    user = db.session.get(User, user_id) or abort(404)
    user.is_active = not user.is_active
    db.session.commit()
    flash(f"{user.username} अकाउंट {'सक्रिय' if user.is_active else 'निष्क्रिय'} कर दिया गया।", "success")
    return redirect(url_for("departments"))


def get_portal_setting(key, default=""):
    setting = PortalSetting.query.filter_by(setting_key=key).first()
    return setting.setting_value if setting else default


def save_portal_setting(key, value):
    setting = PortalSetting.query.filter_by(setting_key=key).first()
    if not setting:
        setting = PortalSetting(setting_key=key, setting_value=value)
        db.session.add(setting)
    else:
        setting.setting_value = value


@app.route("/admin/assets", methods=["GET", "POST"])
@admin_required
def admin_assets():
    if request.method == "POST":
        if "authority_name" in request.form or "authority_designation" in request.form:
            authority_name = request.form.get("authority_name", "").strip()
            authority_designation = request.form.get("authority_designation", "").strip()
            save_portal_setting("authority_name", authority_name[:180])
            save_portal_setting("authority_designation", authority_designation[:180])
        key = request.form.get("asset_key", "")
        uploaded = request.files.get("asset_file")
        if not key and (not uploaded or not uploaded.filename):
            db.session.commit()
            flash("Issuing Authority का नाम और पद सुरक्षित कर दिया गया।", "success")
            return redirect(url_for("admin_assets"))
        if key not in ASSET_OPTIONS or not uploaded or not uploaded.filename:
            flash("सही प्रकार और फाइल चुनें।", "warning")
        else:
            try:
                raw = uploaded.read()
                if len(raw) > 5 * 1024 * 1024:
                    raise ValueError("Image का आकार 5 MB से कम होना चाहिए।")
                im = Image.open(io.BytesIO(raw))
                image_format = im.format
                if image_format not in ("JPEG", "PNG"):
                    raise ValueError("केवल JPG/JPEG या PNG image स्वीकार की जाएगी।")
                im.verify()
                mime = "image/png" if image_format == "PNG" else "image/jpeg"
                asset = StoredAsset.query.filter_by(asset_key=key).first()
                if not asset:
                    asset = StoredAsset(asset_key=key, filename=uploaded.filename, mime_type=mime, data=raw)
                    db.session.add(asset)
                else:
                    asset.filename, asset.mime_type, asset.data = uploaded.filename, mime, raw
                db.session.commit()
                flash(f"{ASSET_OPTIONS[key]} सुरक्षित कर दिया गया।", "success")
                return redirect(url_for("admin_assets"))
            except Exception as exc:
                flash(f"फाइल स्वीकार नहीं हुई: {exc}", "danger")
    db.session.commit()
    assets = {a.asset_key: a for a in StoredAsset.query.all()}
    return render_template("assets.html", assets=assets,
                           authority_name=get_portal_setting("authority_name"),
                           authority_designation=get_portal_setting("authority_designation"))


@app.route("/admin/asset/<key>/delete", methods=["POST"])
@admin_required
def delete_asset(key):
    asset = StoredAsset.query.filter_by(asset_key=key).first()
    if asset:
        db.session.delete(asset)
        db.session.commit()
        flash("फाइल हटा दी गई।", "success")
    return redirect(url_for("admin_assets"))


@app.route("/admin/requests")
@admin_required
def admin_requests():
    requests_list = CardRequest.query.order_by(CardRequest.created_at.desc()).limit(250).all()
    return render_template("admin_requests.html", requests_list=requests_list)


@app.route("/department")
@department_required
def department_dashboard():
    user = current_user()
    total = CardRequest.query.filter_by(requested_by_id=user.id).count()
    recent = CardRequest.query.filter_by(requested_by_id=user.id).order_by(CardRequest.created_at.desc()).limit(8).all()
    return render_template("department_dashboard.html", total=total, recent=recent)


@app.route("/employee/lookup", methods=["POST"])
@department_required
def employee_lookup():
    hrms_id = request.form.get("hrms_id", "").strip().upper().replace(" ", "")
    if not hrms_id:
        flash("कृपया HRMS ID दर्ज करें।", "warning")
        return redirect(url_for("department_dashboard"))
    emp = Employee.query.filter_by(hrms_id=hrms_id).first()
    if not emp:
        flash("यह HRMS ID HRMS Backend में नहीं मिली। Admin से HRMS फाइल अपडेट करवाएँ।", "danger")
        return redirect(url_for("department_dashboard"))
    if normalize_header(emp.department) != normalize_header(current_user().department):
        flash(f"यह कर्मचारी {emp.department} विभाग का है। आपके Login ID को {current_user().department} विभाग की अनुमति है।", "danger")
        return redirect(url_for("department_dashboard"))
    session["lookup_employee_id"] = emp.id
    return render_template("confirm_employee.html", employee=emp)


@app.route("/employee/continue", methods=["POST"])
@department_required
def employee_continue():
    emp = db.session.get(Employee, session.get("lookup_employee_id"))
    if not emp:
        flash("कृपया HRMS ID दोबारा दर्ज करें।", "warning")
        return redirect(url_for("department_dashboard"))
    decision = request.form.get("confirm", "")
    if decision not in ("yes", "no"):
        flash("कृपया Yes या No चुनें।", "warning")
        return render_template("confirm_employee.html", employee=emp)
    return render_template("employee_card_form.html", employee=emp, correction_mode=(decision == "no"))


def compress_photo(file_storage):
    raw = file_storage.read()
    if not raw:
        raise ValueError("कर्मचारी का फोटो अपलोड करें।")
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((700, 900))
    for quality in (88, 82, 76, 70, 64, 58, 52, 46):
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=quality, optimize=True)
        data = out.getvalue()
        if len(data) <= 100 * 1024:
            return data
    raise ValueError("फोटो को 100 KB से कम में compress नहीं किया जा सका।")


@app.route("/employee/submit", methods=["POST"])
@department_required
def employee_submit():
    emp = db.session.get(Employee, session.get("lookup_employee_id"))
    if not emp:
        flash("HRMS रिकॉर्ड समाप्त हो गया। दोबारा HRMS ID दर्ज करें।", "warning")
        return redirect(url_for("department_dashboard"))
    name = request.form.get("name", "").strip()
    designation = request.form.get("designation", "").strip()
    department = request.form.get("department", "").strip()
    station = request.form.get("station", "").strip()
    mobile = request.form.get("mobile", "").strip()
    photo = request.files.get("photo")
    if not all([name, designation, department, station, mobile]):
        flash("Name, Designation, Department, Mobile और Station सभी भरना अनिवार्य है।", "warning")
        return render_template("employee_card_form.html", employee=emp, correction_mode=(request.form.get("correction_mode") == "1"), form_values=request.form)
    digits = "".join(ch for ch in mobile if ch.isdigit())
    if len(digits) < 10 or len(digits) > 15:
        flash("कृपया सही Mobile Number दर्ज करें।", "warning")
        return render_template("employee_card_form.html", employee=emp, correction_mode=(request.form.get("correction_mode") == "1"), form_values=request.form)
    try:
        photo_bytes = compress_photo(photo) if photo and photo.filename else None
        signature_file = request.files.get("employee_signature")
        signature_bytes = compress_photo(signature_file) if signature_file and signature_file.filename else None
        if not photo_bytes:
            raise ValueError("कर्मचारी का फोटो अपलोड करना अनिवार्य है।")
    except Exception as exc:
        flash(f"Photo: {exc}", "danger")
        return render_template("employee_card_form.html", employee=emp, correction_mode=(request.form.get("correction_mode") == "1"), form_values=request.form)

    ref = "BRC-" + datetime.utcnow().strftime("%y%m%d") + "-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(5))
    card = CardRequest(
        request_ref=ref, hrms_id=emp.hrms_id, name=name, designation=designation,
        department=department, pf_no=emp.pf_no, station=station, mobile=digits,
        photo_data=photo_bytes, photo_mime="image/jpeg",
        employee_signature_data=signature_bytes,
        correction_made=(request.form.get("correction_mode") == "1"),
        requested_by_id=current_user().id,
    )
    db.session.add(card)
    db.session.commit()
    session.pop("lookup_employee_id", None)
    return render_template("submission_success.html", card=card)


def draw_fitted_image(pdf, data, x, y, w, h):
    try:
        img = Image.open(io.BytesIO(data))
        iw, ih = img.size
        scale = min(w / iw, h / ih)
        dw, dh = iw * scale, ih * scale
        pdf.drawImage(ImageReader(img), x + (w-dw)/2, y + (h-dh)/2, dw, dh, preserveAspectRatio=True, mask="auto")
    except Exception:
        pass


def draw_background(pdf, key, width, height):
    asset = StoredAsset.query.filter_by(asset_key=key).first()
    if asset:
        try:
            draw_fitted_image(pdf, asset.data, 0, 0, width, height)
        except Exception:
            pass


def fit_text(pdf, text, x, y, max_width, font="Helvetica-Bold", start_size=8, min_size=5.5):
    size = start_size
    while size > min_size and pdf.stringWidth(str(text), font, size) > max_width:
        size -= 0.25
    pdf.setFont(font, size)
    pdf.drawString(x, y, str(text))


def make_card_pdf(card):
    width, height = 85.6 * mm, 54 * mm
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(width, height))
    pdf.setTitle(f"Railway ID Card - {card.hrms_id}")

    # FRONT
    draw_background(pdf, "front_template", width, height)
    if not StoredAsset.query.filter_by(asset_key="front_template").first():
        pdf.setFillColorRGB(1, 1, 1)
        pdf.rect(0, 0, width, height, fill=1, stroke=0)
        pdf.setStrokeColorRGB(0.72, 0.74, 0.80)
        pdf.rect(1.1*mm, 1.1*mm, width-2.2*mm, height-2.2*mm, fill=0, stroke=1)

    left_logo = StoredAsset.query.filter_by(asset_key="railway_logo").first()
    right_logo = StoredAsset.query.filter_by(asset_key="division_logo").first()
    if left_logo:
        draw_fitted_image(pdf, left_logo.data, 2.5*mm, 44.7*mm, 9*mm, 7.2*mm)
    if right_logo:
        draw_fitted_image(pdf, right_logo.data, 74*mm, 44.7*mm, 9*mm, 7.2*mm)

    pdf.setFillColorRGB(0.12, 0.13, 0.22)
    pdf.setFont("Helvetica-Bold", 8.4)
    pdf.drawCentredString(width/2, 47.4*mm, "WESTERN RAILWAY - VADODARA DIVISION")
    pdf.setFillColorRGB(0.27, 0.27, 0.60)
    pdf.rect(1.2*mm, 40.2*mm, width-2.4*mm, 4.0*mm, fill=1, stroke=0)
    pdf.setFillColorRGB(1, 1, 1)
    pdf.setFont("Helvetica-Bold", 8.4)
    pdf.drawString(4*mm, 41.45*mm, "IDENTITY CARD")
    pdf.setFont("Helvetica-Bold", 6.5)
    pdf.drawRightString(width-4*mm, 41.55*mm, f"No. {card.hrms_id}")

    labels = [("Name", card.name), ("Design.", card.designation), ("Depart.", card.department),
              ("Station", card.station), ("PF No.", card.pf_no), ("Mobile No.", card.mobile)]
    y_positions = [35.8, 30.3, 24.8, 19.3, 13.8, 8.3]
    for (label, value), y in zip(labels, y_positions):
        pdf.setFillColorRGB(0.12, 0.12, 0.16)
        pdf.setFont("Helvetica-Bold", 7.1)
        pdf.drawString(3.2*mm, y*mm, label)
        pdf.setFont("Helvetica-Bold", 7.0)
        pdf.drawString(17*mm, y*mm, ":")
        fit_text(pdf, value or "-", 20*mm, y*mm, 36*mm, start_size=7.1, min_size=5.5)

    draw_fitted_image(pdf, card.photo_data, 59.5*mm, 11.5*mm, 21.5*mm, 26.3*mm)
    pdf.setStrokeColorRGB(0.35, 0.35, 0.4)
    pdf.rect(59.2*mm, 11.2*mm, 22.1*mm, 26.9*mm, fill=0, stroke=1)
    # Employee signature (optional) and issuing authority signature/details.
    if card.employee_signature_data:
        draw_fitted_image(pdf, card.employee_signature_data, 4*mm, 1.8*mm, 20*mm, 5.2*mm)
    pdf.setFillColorRGB(0.2, 0.2, 0.2)
    pdf.setFont("Helvetica", 4.8)
    pdf.drawString(4*mm, 1.2*mm, "Employee Signature")
    authority = StoredAsset.query.filter_by(asset_key="authority_signature").first()
    if authority:
        draw_fitted_image(pdf, authority.data, 60*mm, 5.0*mm, 21*mm, 5.5*mm)
    pdf.setFont("Helvetica-Bold", 5.0)
    pdf.drawCentredString(70.5*mm, 4.0*mm, get_portal_setting("authority_name") or "Issuing Authority")
    pdf.setFont("Helvetica", 4.6)
    pdf.drawCentredString(70.5*mm, 2.0*mm, get_portal_setting("authority_designation") or "")
    pdf.showPage()

    # BACK
    draw_background(pdf, "back_template", width, height)
    if not StoredAsset.query.filter_by(asset_key="back_template").first():
        pdf.setFillColorRGB(1, 1, 1)
        pdf.rect(0, 0, width, height, fill=1, stroke=0)
        pdf.setStrokeColorRGB(0.72, 0.74, 0.80)
        pdf.rect(1.1*mm, 1.1*mm, width-2.2*mm, height-2.2*mm, fill=0, stroke=1)
    pdf.setFillColorRGB(0.16, 0.16, 0.19)
    pdf.setFont("Helvetica-BoldOblique", 8.2)
    pdf.drawCentredString(width/2, 47*mm, "If Found Unattended Please Return To")
    pdf.setFont("Helvetica-BoldOblique", 7.6)
    pdf.drawCentredString(width/2, 42.8*mm, "Station Master of Nearest Railway Station")
    pdf.setFont("Helvetica-BoldOblique", 7.4)
    pdf.drawCentredString(width/2, 38.9*mm, "or Senior Divisional Personnel Officer")
    pdf.setFont("Helvetica-Bold", 6.7)
    pdf.drawCentredString(width/2, 34.8*mm, "Second Floor, DRM Office, Western Railway")
    pdf.drawCentredString(width/2, 31.4*mm, "Pratap Nagar, Vadodara - 390004")

    qr_payload = {
        "HRMS_ID": card.hrms_id,
        "NAME": card.name,
        "DESIGNATION": card.designation,
        "DEPARTMENT": card.department,
        "STATION": card.station,
        "PF_NO": card.pf_no,
        "MOBILE_NO": card.mobile,
        "DIVISION": "Vadodara Division, Western Railway",
    }
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=5, border=2)
    qr.add_data(json.dumps(qr_payload, ensure_ascii=False, separators=(",", ":")))
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    qr_size = 22*mm
    draw_fitted_image(pdf, qr_buffer.getvalue(), (width-qr_size)/2, 4.5*mm, qr_size, qr_size)
    pdf.setFont("Helvetica", 5.2)
    pdf.drawCentredString(width/2, 2.6*mm, "Scan QR Code for employee details")
    pdf.showPage()
    pdf.save()
    output.seek(0)
    return output


def can_access_card(card):
    user = current_user()
    if user.role != "admin" and card.requested_by_id != user.id:
        abort(403)


@app.route("/card/<int:card_id>/preview")
@login_required
def card_preview(card_id):
    card = db.session.get(CardRequest, card_id) or abort(404)
    can_access_card(card)
    return render_template("card_preview.html", card=card)


@app.route("/card/<int:card_id>/preview.pdf")
@login_required
def card_preview_pdf(card_id):
    card = db.session.get(CardRequest, card_id) or abort(404)
    can_access_card(card)
    return send_file(make_card_pdf(card), mimetype="application/pdf", as_attachment=False)


@app.route("/card/<int:card_id>/confirm", methods=["POST"])
@login_required
def confirm_card_preview(card_id):
    card = db.session.get(CardRequest, card_id) or abort(404)
    can_access_card(card)
    if request.form.get("confirm_preview") != "yes":
        flash("PDF डाउनलोड करने से पहले Front और Back Preview की पुष्टि करें।", "warning")
        return redirect(url_for("card_preview", card_id=card.id))
    session.setdefault("confirmed_card_previews", [])
    confirmed = session["confirmed_card_previews"]
    if card.id not in confirmed:
        confirmed.append(card.id)
    session["confirmed_card_previews"] = confirmed[-50:]
    flash("Preview confirmed. अब Final PDF डाउनलोड कर सकते हैं।", "success")
    return redirect(url_for("card_preview", card_id=card.id))


@app.route("/card/<int:card_id>.pdf")
@login_required
def download_card(card_id):
    card = db.session.get(CardRequest, card_id) or abort(404)
    can_access_card(card)
    if card.id not in session.get("confirmed_card_previews", []):
        flash("पहले Front और Back Preview देखकर Confirm करें।", "warning")
        return redirect(url_for("card_preview", card_id=card.id))
    pdf_file = make_card_pdf(card)
    return send_file(pdf_file, mimetype="application/pdf", as_attachment=True,
                     download_name=f"Railway_ID_Card_{card.hrms_id}.pdf")


@app.route("/admin/asset-preview/<key>")
@admin_required
def admin_asset_preview(key):
    asset = StoredAsset.query.filter_by(asset_key=key).first_or_404()
    return send_file(io.BytesIO(asset.data), mimetype=asset.mime_type, download_name=asset.filename)


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="आपको इस पेज को देखने की अनुमति नहीं है।"), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="मांगा गया पेज उपलब्ध नहीं है।"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")
