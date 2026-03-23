from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room, leave_room
import pandas as pd
import bcrypt
import jwt
import datetime
from functools import wraps
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///auction.db'
app.config['SECRET_KEY'] = 'your_secret_key'
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    balance = db.Column(db.Integer, default=10000000)  # Virtual budget

class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    base_price = db.Column(db.Integer, nullable=False)
    role = db.Column(db.String(50))
    team = db.Column(db.String(100), nullable=True)
    highest_bid = db.Column(db.Integer, nullable=True)
    highest_bidder = db.Column(db.String(50), nullable=True)

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    host = db.Column(db.String(50), nullable=False)
    room_code = db.Column(db.String(10), unique=True, nullable=False)

# Authentication Decorator
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('x-access-token')
        if not token:
            return jsonify({"message": "Token is missing!"}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = data['username']
        except:
            return jsonify({"message": "Token is invalid!"}), 401
        return f(current_user, *args, **kwargs)
    return decorated

# User Registration
@app.route("/register", methods=["POST"])
def register():
    data = request.json
    username = data["username"]
    password = data["password"].encode('utf-8')
    hashed_pw = bcrypt.hashpw(password, bcrypt.gensalt())
    
    user = User(username=username, password=hashed_pw)
    db.session.add(user)
    try:
        db.session.commit()
    except:
        return jsonify({"message": "Username already exists."}), 400
    
    return jsonify({"message": "User registered successfully!"})

# User Login
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    username = data["username"]
    password = data["password"].encode('utf-8')
    
    user = User.query.filter_by(username=username).first()
    
    if user and bcrypt.checkpw(password, user.password.encode('utf-8')):
        token = jwt.encode({"username": username, "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)}, app.config['SECRET_KEY'], algorithm="HS256")
        return jsonify({"token": token})
    else:
        return jsonify({"message": "Invalid credentials."}), 401

# Host a Room
@app.route("/host", methods=["POST"])
@token_required
def host_room(current_user):
    room_code = os.urandom(4).hex()
    new_room = Room(host=current_user, room_code=room_code)
    db.session.add(new_room)
    db.session.commit()
    return jsonify({"room_code": room_code, "message": "Room hosted successfully!"})

# Join a Room
@app.route("/join", methods=["GET"])
def join_room_list():
    rooms = Room.query.all()
    room_list = [{"host": room.host, "room_code": room.room_code} for room in rooms]
    return jsonify({"rooms": room_list})

# Upload Player Data
@app.route("/upload", methods=["POST"])
@token_required
def upload_players(current_user):
    file = request.files["file"]
    df = pd.read_excel(file)
    
    for _, row in df.iterrows():
        player = Player(name=row["Name"], base_price=row["Base Price"], role=row["Role"])
        db.session.add(player)
    db.session.commit()
    
    return jsonify({"message": "Players uploaded successfully!"})

# Assign Team to Player
@app.route("/assign_team", methods=["POST"])
@token_required
def assign_team(current_user):
    data = request.json
    player_id = data["player_id"]
    team_name = data["team"]
    
    player = Player.query.get(player_id)
    if player:
        player.team = team_name
        db.session.commit()
        return jsonify({"message": "Team assigned successfully!"})
    return jsonify({"message": "Player not found."}), 404

# Place a Bid
@app.route("/place_bid", methods=["POST"])
@token_required
def place_bid(current_user):
    data = request.json
    player_id = data["player_id"]
    bid_amount = data["bid_amount"]
    
    player = Player.query.get(player_id)
    if not player:
        return jsonify({"message": "Player not found."}), 404
    
    if player.highest_bid is None or bid_amount > player.highest_bid:
        player.highest_bid = bid_amount
        player.highest_bidder = current_user
        db.session.commit()
        
        bid_data = {"player_id": player_id, "bid_amount": bid_amount, "bidder": current_user}
        socketio.emit("update", bid_data, broadcast=True)
        return jsonify({"message": "Bid placed successfully!"})
    else:
        return jsonify({"message": "Bid must be higher than the current highest bid."}), 400

@socketio.on("bid")
def handle_bid(data):
    emit("update", data, broadcast=True)

if __name__ == "__main__":
    db.create_all()
    socketio.run(app, debug=True)
