from flask import Flask, request, jsonify
from flask_cors import CORS
import os
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from db import db
from models import User, Collaboration


load_dotenv()
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///musicconnectz.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)
db.init_app(app)

# Homepage route
@app.route("/")
def home():
    return "Welcome to Music ConnectZ Backend!"
from dotenv import load_dotenv
load_dotenv()

# --- Test password signup/login ---
@app.route('/test/password-auth', methods=['POST'])
def test_password_auth():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    name = data.get('name', 'Test User')
    # Signup
    user = User.query.filter_by(email=email).first()
    if not user:
        hashed_pw = generate_password_hash(password)
        user = User(email=email, password=hashed_pw, name=name)
        db.session.add(user)
        db.session.commit()
    # Login
    user = User.query.filter_by(email=email).first()
    if user and check_password_hash(user.password, password):
        return jsonify({'message': 'Password auth test successful', 'user': {'email': user.email, 'name': user.name}}), 200
    else:
        return jsonify({'error': 'Password auth test failed'}), 401

from flask_dance.contrib.google import make_google_blueprint, google
from flask_dance.contrib.facebook import make_facebook_blueprint, facebook
from flask_dance.contrib.spotify import make_spotify_blueprint, spotify

import os
# Social login blueprints (now using environment variables for Google)
google_bp = make_google_blueprint(
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    redirect_to="google_login"
)
facebook_bp = make_facebook_blueprint(client_id="FACEBOOK_CLIENT_ID", client_secret="FACEBOOK_CLIENT_SECRET", redirect_to="facebook_login")
spotify_bp = make_spotify_blueprint(client_id="SPOTIFY_CLIENT_ID", client_secret="SPOTIFY_CLIENT_SECRET", redirect_to="spotify_login")


app.register_blueprint(google_bp, url_prefix="/login")
app.register_blueprint(facebook_bp, url_prefix="/login")
app.register_blueprint(spotify_bp, url_prefix="/login")

# --- API endpoints for frontend social login integration ---
@app.route('/api/auth/google/available', methods=['GET'])
def google_available():
    # Check if Google OAuth is configured
    enabled = bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))
    return jsonify({"enabled": enabled}), 200

@app.route('/api/auth/google')
def api_auth_google():
    # Redirect to Google OAuth login
    # This will use Flask-Dance's blueprint
    return google_bp.session.authorized or google.authorized or google_bp.session.token
    # Actually, redirect to /login/google to start OAuth
    from flask import redirect
    return redirect('/login/google')

@app.route('/api/auth/google/callback')
def api_auth_google_callback():
    # This route is not strictly needed, Flask-Dance handles callback at /login/google/authorized
    # But for frontend, we can redirect here after login
    from flask import redirect, url_for
    return redirect(url_for('google_login'))

# Social login callback routes (stubs)

# This is the callback route for Google OAuth
@app.route("/login/google/authorized")
def google_login():
    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        return jsonify({"error": "Google login failed"}), 400
    userinfo = resp.json()
    email = userinfo.get("email")
    # Here you would create or update user in SQL database if needed
    # For frontend integration, redirect to frontend with user info in URL
    from flask import redirect, url_for
    import urllib.parse, json
    user_param = urllib.parse.quote(json.dumps(userinfo))
    # Redirect to frontend with user info and success flag
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:8000/index.html")
    return redirect(f"{frontend_url}?social_login=success&user={user_param}")

@app.route("/login/facebook/authorized")
def facebook_login():
    resp = facebook.get("/me?fields=id,name,email")
    if not resp.ok:
        return jsonify({"error": "Facebook login failed"}), 400
    return jsonify(resp.json()), 200


@app.route("/login/spotify/authorized")
def spotify_login():
    resp = spotify.get("/v1/me")
    if not resp.ok:
        return jsonify({"error": "Spotify login failed"}), 400
    return jsonify(resp.json()), 200
# --- Social APIs ---
@app.route('/api/social/users', methods=['GET'])
def get_all_users():
    users = User.query.all()
    users_list = [{'id': u.id, 'email': u.email, 'name': u.name, 'premium': u.premium} for u in users]
    return jsonify({'users': users_list}), 200

@app.route('/api/social/collaborations', methods=['GET'])
def get_all_collaborations():
    collabs = Collaboration.query.all()
    collabs_list = [{'id': c.id, 'title': c.title, 'description': c.description, 'user_id': c.user_id} for c in collabs]
    return jsonify({'collaborations': collabs_list}), 200

# --- Authentication Endpoints ---
@app.route('/auth/signup', methods=['POST'])
def signup():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    name = data.get('name')
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'User already exists'}), 409
    hashed_pw = generate_password_hash(password)
    user = User(email=email, password=hashed_pw, name=name, premium=False)
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'Signup successful'}), 201

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({'error': 'Invalid credentials'}), 401
    return jsonify({'message': 'Login successful', 'user': {'email': user.email, 'name': user.name, 'premium': user.premium}}), 200

# --- User Management ---

@app.route('/api/profile/<user_id>', methods=['GET'])
def get_profile(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'id': user.id, 'email': user.email, 'name': user.name, 'premium': user.premium}), 200


@app.route('/api/profile', methods=['PUT'])
def update_profile():
    data = request.get_json()
    user_id = data.get('id')
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    user.name = data.get('name', user.name)
    user.premium = data.get('premium', user.premium)
    db.session.commit()
    return jsonify({'message': 'Profile updated'}), 200


@app.route('/api/user-data', methods=['GET'])
def get_user_data():
    email = request.args.get('email')
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify({'id': user.id, 'email': user.email, 'name': user.name, 'premium': user.premium}), 200

# --- Collaborations ---

@app.route('/api/collaborations', methods=['GET', 'POST'])
def collaborations():
    if request.method == 'GET':
        collabs = Collaboration.query.all()
        collabs_list = [{'id': c.id, 'title': c.title, 'description': c.description, 'user_id': c.user_id} for c in collabs]
        return jsonify({'collaborations': collabs_list}), 200
    elif request.method == 'POST':
        data = request.get_json()
        title = data.get('title')
        description = data.get('description')
        user_id = data.get('user_id')
        collab = Collaboration(title=title, description=description, user_id=user_id)
        db.session.add(collab)
        db.session.commit()
        return jsonify({'message': 'Collaboration created', 'id': collab.id}), 201


@app.route('/api/collaborations/<collab_id>', methods=['PUT', 'DELETE'])
def update_delete_collab(collab_id):
    collab = Collaboration.query.get(collab_id)
    if not collab:
        return jsonify({'error': 'Collaboration not found'}), 404
    if request.method == 'PUT':
        data = request.get_json()
        collab.title = data.get('title', collab.title)
        collab.description = data.get('description', collab.description)
        db.session.commit()
        return jsonify({'message': f'Collaboration {collab_id} updated'}), 200
    elif request.method == 'DELETE':
        db.session.delete(collab)
        db.session.commit()
        return jsonify({'message': f'Collaboration {collab_id} deleted'}), 200

# --- Messaging (Premium) ---
@app.route('/api/messages', methods=['GET', 'POST'])
def messages():
    if request.method == 'GET':
        # TODO: Get messages
        return jsonify({'message': 'Get messages'}), 200
    elif request.method == 'POST':
        # TODO: Send message
        return jsonify({'message': 'Send message'}), 201

# --- Membership & Payments ---
@app.route('/api/membership', methods=['GET'])
def get_membership():
    # TODO: Get membership status
    return jsonify({'message': 'Get membership status'}), 200

@app.route('/api/membership/checkout', methods=['POST'])
def membership_checkout():
    # TODO: Create Stripe checkout
    return jsonify({'message': 'Create Stripe checkout'}), 200

@app.route('/webhooks/stripe', methods=['POST'])
def stripe_webhook():
    # TODO: Handle Stripe webhook
    return jsonify({'message': 'Stripe webhook received'}), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
