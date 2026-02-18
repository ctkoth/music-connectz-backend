
from flask import Flask, jsonify
from pymongo import MongoClient
import os



app = Flask(__name__)

# MongoDB connection string (replace with your actual URI or use environment variable)
MONGO_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/musicdb')
client = MongoClient(MONGO_URI)
db = client.get_database()

@app.route('/')
def home():
    return 'Hello from Python Flask backend!'

@app.route('/api/hello')
def api_hello():
    return {'message': 'Hello from the API!'}


# Example MongoDB endpoint
@app.route('/api/mongo-test')
def mongo_test():
    # Insert a test document and retrieve all documents
    db.test.insert_one({'msg': 'Hello, MongoDB!'})
    docs = list(db.test.find({}, {'_id': 0}))
    return jsonify(docs)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)