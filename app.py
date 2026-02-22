from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from flask_cors import CORS
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)
# MongoDB connection string
MONGO_URI = "mongodb://localhost:27017/musicconnectz"
app.config['MONGO_URI'] = MONGO_URI
mongo = PyMongo(app)

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
    if not mongo.db.users.find_one({'email': email}):
        hashed_pw = generate_password_hash(password)
        mongo.db.users.insert_one({'email': email, 'password': hashed_pw, 'name': name})
    # Login
    user = mongo.db.users.find_one({'email': email})
    if user and check_password_hash(user['password'], password):
        return jsonify({'message': 'Password auth test successful', 'user': {'email': user['email'], 'name': user['name']}}), 200
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

# Social login callback routes (stubs)
@app.route("/login/google/authorized")
def google_login():
    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        return jsonify({"error": "Google login failed"}), 400
    userinfo = resp.json()
    email = userinfo.get("email")
    if email:
        # Create or update user in MongoDB
        mongo.db.users.update_one(
            {"email": email},
            {"$set": {"name": userinfo.get("name", "Google User"), "google_id": userinfo.get("id")}},
            upsert=True
        )
    return jsonify(userinfo), 200

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
    users = list(mongo.db.users.find({}, {'password': 0}))
    for user in users:
        user['_id'] = str(user['_id'])
    return jsonify({'users': users}), 200

@app.route('/api/social/collaborations', methods=['GET'])
def get_all_collaborations():
    collabs = list(mongo.db.collaborations.find({}))
    for c in collabs:
        c['_id'] = str(c['_id'])
    return jsonify({'collaborations': collabs}), 200

# --- Authentication Endpoints ---
@app.route('/auth/signup', methods=['POST'])
def signup():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    name = data.get('name')
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    if mongo.db.users.find_one({'email': email}):
        return jsonify({'error': 'User already exists'}), 409
    hashed_pw = generate_password_hash(password)
    user = {'email': email, 'password': hashed_pw, 'name': name, 'premium': False}
    mongo.db.users.insert_one(user)
    return jsonify({'message': 'Signup successful'}), 201

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    user = mongo.db.users.find_one({'email': email})
    if not user or not check_password_hash(user['password'], password):
        return jsonify({'error': 'Invalid credentials'}), 401
    # For demo: return user info (do not return password in production)
    return jsonify({'message': 'Login successful', 'user': {'email': user['email'], 'name': user.get('name'), 'premium': user.get('premium', False)}}), 200

# --- User Management ---
@app.route('/api/profile/<user_id>', methods=['GET'])
def get_profile(user_id):
    # TODO: Fetch user profile
    return jsonify({'message': f'Get profile for {user_id}'}), 200

@app.route('/api/profile', methods=['PUT'])
def update_profile():
    # TODO: Update user profile
    return jsonify({'message': 'Update profile'}), 200

@app.route('/api/user-data', methods=['GET'])
def get_user_data():
    # TODO: Get current user data
    return jsonify({'message': 'Get user data'}), 200

# --- Collaborations ---
@app.route('/api/collaborations', methods=['GET', 'POST'])
def collaborations():
    if request.method == 'GET':
        # TODO: List all collaborations
        return jsonify({'message': 'List collaborations'}), 200
    elif request.method == 'POST':
        # TODO: Create collaboration
        return jsonify({'message': 'Create collaboration'}), 201

@app.route('/api/collaborations/<collab_id>', methods=['PUT', 'DELETE'])
def update_delete_collab(collab_id):
    if request.method == 'PUT':
        # TODO: Update collaboration
        return jsonify({'message': f'Update collaboration {collab_id}'}), 200
    elif request.method == 'DELETE':
        # TODO: Delete collaboration
        return jsonify({'message': f'Delete collaboration {collab_id}'}), 200

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
    app.run(debug=True)
