
from flask import Flask, request, jsonify, send_from_directory
import webbrowser
import threading
import os

app = Flask(__name__, static_folder='.', static_url_path='')

@app.route('/')
def root():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def static_proxy(path):
    return send_from_directory('.', path)

# Example register endpoint
@app.route('/api/auth/register/', methods=['POST'])
def register():
    data = request.get_json()
    # Here you would add logic to register the user (e.g., save to DB)
    # For now, just echo back the data
    return jsonify({"status": "success", "data": data}), 201

def open_browser():
    webbrowser.open('http://localhost:8000/')

if __name__ == "__main__":
    threading.Timer(1.0, open_browser).start()
    app.run(port=8000, debug=True)
