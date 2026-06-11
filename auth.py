import os
import sqlite3
import datetime
import jwt
from functools import wraps
from flask import Blueprint, request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash

# Declare Blueprint for auth routes
auth_bp = Blueprint('auth', __name__)

DB_PATH = os.path.join("downloads", "users.db")
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "video_agent_jwt_auth_secret_key_extremely_secure_2026")
JWT_ALGORITHM = "HS256"

# Database initialization to create user table
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# Decorator to secure routes using JWT
def jwt_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        # Check headers to extract authorization token
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ")[1]
        
        # If token is not present, block the request
        if not token:
            return jsonify({"error": "You are not logged in. Token is missing!"}), 401
            
        try:
            # Verify token with secret key
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            request.user_id = payload['user_id']
            request.username = payload['username']
        except jwt.ExpiredSignatureError:
            # Handle expired token case
            return jsonify({"error": "Your session has expired. Please login again."}), 401
        except jwt.InvalidTokenError:
            # Handle invalid token case
            return jsonify({"error": "Invalid token details! Please login again."}), 401
            
        return f(*args, **kwargs)
    return decorated

# Registration endpoint for signup
@auth_bp.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    
    if not username or not password:
        return jsonify({"error": "Both username and password are required!"}), 400
        
    hashed_pwd = generate_password_hash(password)
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_pwd))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "Signed up successfully! Please login now."})
    except sqlite3.IntegrityError:
        return jsonify({"error": "This username is already taken. Please try another one."}), 400
    except Exception as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500

# Login endpoint to generate JWT
@auth_bp.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    
    if not username or not password:
        return jsonify({"error": "Both username and password must be shared!"}), 400
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, password FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    
    if row and check_password_hash(row[1], password):
        token_payload = {
            "user_id": row[0],
            "username": username,
            "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=30)
        }
        token = jwt.encode(token_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
        return jsonify({
            "success": True,
            "token": token,
            "username": username,
            "message": "Login done!"
        })
    else:
        return jsonify({"error": "Invalid username or password."}), 401
