from flask import Flask, render_template, request, redirect, flash, url_for, send_file, jsonify, session
import os
from werkzeug.utils import secure_filename
import csv
import io
import requests
import uuid
import json
from functools import wraps
import psycopg2
from psycopg2.extras import DictCursor
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = 'iqbal_patel_super_secret_key_2027_vsw'

# ==========================================
# 📁 FILE UPLOAD CONFIGURATION
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==========================================
# 🗄️ DATABASE CONFIGURATION (POSTGRESQL)
# ==========================================
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL is missing! Please add PostgreSQL on Render.")
    
    if DATABASE_URL.startswith("postgres://"):
        db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    else:
        db_url = DATABASE_URL
        
    url = urlparse(db_url)
    conn = psycopg2.connect(
        database=url.path[1:],
        user=url.username,
        password=url.password,
        host=url.hostname,
        port=url.port
    )
    return conn

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def initialize_database():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''  
            CREATE TABLE IF NOT EXISTS students (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                father_name TEXT NOT NULL,
                dob TEXT NOT NULL,
                class TEXT NOT NULL,
                gender TEXT NOT NULL,
                academic_year TEXT NOT NULL,
                aadhar TEXT NOT NULL,
                village TEXT NOT NULL,
                taluka TEXT NOT NULL,
                district TEXT NOT NULL,
                pin TEXT NOT NULL,
                religion TEXT NOT NULL,
                caste TEXT NOT NULL,
                nationality TEXT NOT NULL,
                mother_tongue TEXT NOT NULL,
                medium TEXT NOT NULL,
                residential_address TEXT NOT NULL,
                phone1 TEXT NOT NULL,
                phone2 TEXT,
                photo TEXT NOT NULL,
                signature TEXT NOT NULL,
                payment_utr TEXT UNIQUE NOT NULL,
                hall_ticket TEXT UNIQUE,
                verified BOOLEAN DEFAULT FALSE,
                exam_center TEXT NOT NULL,
                admission_phase TEXT NOT NULL
            );
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        print("PostgreSQL Database initialized successfully!")
    except Exception as e:
        print(f"Database initialization error: {e}")

# ========== Admin Login Decorator ==========
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            flash('Please log in to access this page.', 'danger')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ========== PhonePe Configuration ==========
def load_phonepe_config():
    if os.path.exists('phonepe_config.json'):
        with open('phonepe_config.json', 'r') as f:
            return json.load(f)
    return {}

def save_phonepe_config_to_file(config):
    with open('phonepe_config.json', 'w') as f:
        json.dump(config, f)

def get_phonepe_access_token(client_id, client_secret, client_version, env='sandbox'):
    if env == 'production':
        url = "https://api.phonepe.com/apis/identity-manager/v1/oauth/token"
    else:
        url = "https://api-preprod.phonepe.com/apis/pg-sandbox/v1/oauth/token"

    payload = {
        'client_id': client_id,
        'client_version': client_version,
        'client_secret': client_secret,
        'grant_type': 'client_credentials'
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    resp = requests.post(url, data=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json().get('access_token')

def phonepe_generate_upi_qr(amount_paise, merchant_order_id):
    config = load_phonepe_config()
    if not config.get('client_id'):
        return {"success": False, "error": "PhonePe not configured."}

    env = config.get('env', 'sandbox')
    base = "https://api.phonepe.com/apis/pg" if env == 'production' else "https://api-preprod.phonepe.com/apis/pg-sandbox"

    try:
        token = get_phonepe_access_token(
            config['client_id'], config['client_secret'],
            config.get('client_version', '1'), env
        )
    except Exception as e:
        return {"success": False, "error": f"Auth failed: {str(e)}"}

    url = f"{base}/payments/v2/pay"
    payload = {
        "merchantOrderId": merchant_order_id,
        "amount": amount_paise,
        "expireAfter": 600,
        "paymentFlow": {"type": "PG"},
        "paymentMode": {"type": "UPI_QR"}
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"O-Bearer {token}",
        "X-MERCHANT-ID": config.get('merchant_id', '') 
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return {
            "success": True,
            "qrData": data.get("qrData", ""),
            "intentUrl": data.get("intentUrl", ""),
            "orderId": data.get("orderId", "")
        }
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)}

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store'
    return response

# ========== Routes ==========
@app.route('/')
def register():
    return render_template('register.html')

@app.route('/register', methods=['POST'])
def register_student():
    try:
        student_data = {k: request.form[k] for k in request.form}
        photo = request.files.get('photo')
        signature = request.files.get('signature')

        if not all([photo, signature]):
            flash("Both photo and signature must be uploaded.", "danger")
            return redirect(url_for('register'))

        if not (allowed_file(photo.filename) and allowed_file(signature.filename)):
            flash("Only PNG, JPG, and JPEG files are allowed.", "danger")
            return redirect(url_for('register'))

        photo_filename = secure_filename(photo.filename)
        signature_filename = secure_filename(signature.filename)
        photo_path = os.path.join(UPLOAD_FOLDER, photo_filename)
        signature_path = os.path.join(UPLOAD_FOLDER, signature_filename)

        photo.save(photo_path)
        signature.save(signature_path)
        
        # Save relative paths for the database
        photo_db_path = f"static/uploads/{photo_filename}"
        signature_db_path = f"static/uploads/{signature_filename}"

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)
        
        cursor.execute(""" 
            INSERT INTO students (
                name, father_name, dob, class, gender, academic_year, aadhar, village, taluka, district, pin,
                religion, caste, nationality, mother_tongue, medium, residential_address, phone1, phone2,
                photo, signature, payment_utr, exam_center, admission_phase
            ) VALUES (
                %(name)s, %(father_name)s, %(dob)s, %(class)s, %(gender)s, %(academic_year)s, %(aadhar)s, %(village)s, %(taluka)s, %(district)s, %(pin)s,
                %(religion)s, %(caste)s, %(nationality)s, %(mother_tongue)s, %(medium)s, %(residential_address)s, %(phone1)s, %(phone2)s,
                %(photo)s, %(signature)s, %(payment_utr)s, %(exam_center)s, %(admission_phase)s
            ) RETURNING id
        """, {
            **student_data,
            'photo': photo_db_path,
            'signature': signature_db_path,
            'payment_utr': student_data.get('payment_utr'),
            'exam_center': student_data.get('exam_center'),
            'admission_phase': student_data.get('admission_phase', 'Phase_1')
        })
        
        student_id = cursor.fetchone()['id']
        hall_ticket = f"HT-{student_id:06}"
        cursor.execute("UPDATE students SET hall_ticket = %s WHERE id = %s", (hall_ticket, student_id))
        conn.commit()
        cursor.close()
        conn.close()

        # Securely allow the student to view their own ticket
        session['recent_student_id'] = student_id
        flash(f"Form submitted successfully! Hall Ticket: {hall_ticket}", "success")
        return redirect(url_for('view_hall_ticket', student_id=student_id))

    except Exception as e:
        print(f"REGISTRATION ERROR: {e}") # This prints to Render logs
        flash(f"An error occurred: {e}", "danger")
        return redirect(url_for('register'))

@app.route('/hallticket/<int:student_id>')
def view_hall_ticket(student_id):
    # Security: Allow Admin OR the student who just registered
    if 'admin_logged_in' not in session and session.get('recent_student_id') != student_id:
        flash('Unauthorized access. Please register to view your ticket.', 'danger')
        return redirect(url_for('register'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM students WHERE id = %s", (student_id,))
    student = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not student:
        flash("Student not found.", "danger")
        return redirect(url_for('register'))
        
    return render_template('hallticket.html', student=student)

# ========== Admin Routes ==========
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == 'admin' and password == 'iqbal2027':
            session['admin_logged_in'] = True
            flash('Logged in successfully.', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid credentials. Please try again.', 'danger')
            
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('admin_login'))

@app.route('/admin')
@login_required
def admin_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM students ORDER BY id DESC")
    students = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('admin.html', students=students)

@app.route('/admin/verify/<int:student_id>', methods=['POST'])
@login_required
def verify_student(student_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE students SET verified = TRUE WHERE id = %s", (student_id,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Student data verified successfully!", "success")
    except Exception as e:
        flash(f"An error occurred while verifying: {e}", "danger")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/generate_hall_ticket/<int:student_id>', methods=['POST'])
@login_required
def generate_hall_ticket(student_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT * FROM students WHERE id = %s", (student_id,))
        student = cursor.fetchone()
        
        if student and student['verified']:
            hall_ticket = f"HT-{student_id:06}"
            cursor.execute("UPDATE students SET hall_ticket = %s WHERE id = %s", (hall_ticket, student_id))
            conn.commit()
            flash(f"Hall Ticket Generated: {hall_ticket}", "success")
        else:
            flash("Student data is not verified or doesn't exist.", "danger")
            
        cursor.close()
        conn.close()
        
        if student and student['verified']:
            return redirect(url_for('view_hall_ticket', student_id=student_id))
            
    except Exception as e:
        flash(f"An error occurred: {e}", "danger")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/download_csv', methods=['GET'])
@login_required
def download_csv():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT id, hall_ticket, name, class, payment_utr, verified FROM students")
        students = cursor.fetchall()
        cursor.close()
        conn.close()

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["ID", "Hall Ticket Number", "Name", "Class", "UTR Number", "Status"])
        writer.writeheader()
        for student in students:
            writer.writerow({
                "ID": student["id"],
                "Hall Ticket Number": student["hall_ticket"],
                "Name": student["name"],
                "Class": student["class"],
                "UTR Number": student["payment_utr"],
                "Status": "Verified" if student["verified"] else "Not Verified"
            })
        output.seek(0)

        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name='registered_students.csv'
        )
    except Exception as e:
        flash(f"An error occurred while generating CSV: {e}", "danger")
        return redirect(url_for('admin_dashboard'))

@app.route('/admin/payment_info')
@login_required
def payment_info():
    return render_template('payment_info.html')

# ========== PhonePe Routes ==========
@app.route('/admin/save_phonepe_config', methods=['POST'])
@login_required
def save_phonepe_config():
    try:
        data = request.get_json()
        save_phonepe_config_to_file(data)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/admin/generate_payment_qr', methods=['POST'])
@login_required
def admin_generate_payment_qr():
    try:
        req = request.get_json() or {}
        amount = int(req.get('amount', 100))
        order_id = f"ADMIN_{uuid.uuid4().hex[:12].upper()}"
        result = phonepe_generate_upi_qr(amount, order_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ==========================================
# CRITICAL: INITIALIZE DATABASE ON STARTUP
# ==========================================
initialize_database()

if __name__ == '__main__':
    app.run(debug=True)