

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import webbrowser
import threading
import os

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app, origins=["https://musicconnectz.net"])

@app.route('/')
def root():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def static_proxy(path):
    return send_from_directory('.', path)

@app.route('/api/auth/register/', methods=['POST'])
def register():
    try:
        data = request.get_json(force=True)
        if not data or 'email' not in data or 'password' not in data:
            return jsonify({"status": "error", "message": "Missing email or password"}), 400
        # Here you would add logic to register the user (e.g., save to DB)
        return jsonify({"status": "success", "data": data}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def open_browser():
    webbrowser.open('http://localhost:8000/')

if __name__ == "__main__":
    threading.Timer(1.0, open_browser).start()
    app.run(port=8000, debug=True)
