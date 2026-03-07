# Simple Python HTTP Server for Local Testing
# Usage: python simple_server.py

import http.server
import socketserver
import webbrowser
import threading
import sys

PORT = 8000
Handler = http.server.SimpleHTTPRequestHandler

def open_browser():
    webbrowser.open(f'http://localhost:{PORT}/index.html')

def run_server():
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving at http://localhost:{PORT}/index.html (Ctrl+C to stop)")
        httpd.serve_forever()

if __name__ == "__main__":
    threading.Timer(1.0, open_browser).start()
    try:
        run_server()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        sys.exit(0)
