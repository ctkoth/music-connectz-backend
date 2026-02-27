# Music ConnectZ Python Backend (Flask)

## Setup

1. Create a virtual environment (optional but recommended):
   python -m venv venv
   
2. Activate the virtual environment:
   - Windows: venv\Scripts\activate
   - Mac/Linux: source venv/bin/activate

3. Install dependencies:
   pip install -r requirements.txt

4. Run the server locally:
   python app.py

For production, your backend is deployed at:
   https://music-connectz-backend-1.onrender.com

To test password authentication, send a POST request to:
   https://music-connectz-backend-1.onrender.com/test/password-auth

with JSON body:
   {
     "email": "your@email.com",
     "password": "yourpassword",
     "name": "Your Name"
   }

## Endpoints
- /auth/signup [POST]
- /auth/login [POST]
- /api/profile/<user_id> [GET]
- /api/profile [PUT]
- /api/user-data [GET]
- /api/collaborations [GET, POST]
- /api/collaborations/<collab_id> [PUT, DELETE]
- /api/messages [GET, POST]
- /api/membership [GET]
- /api/membership/checkout [POST]
- /webhooks/stripe [POST]

## Note
- All endpoints are stubs. You must implement logic for authentication, data storage, and payments.
- For real-time messaging, consider Flask-SocketIO.
- For database, use SQLite, PostgreSQL, or similar.
