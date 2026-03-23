import socket
import threading
import pandas as pd
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


file_path = r"F:\\new project\\ipl auction\\newwwwwwwwwwwww\\IPLPlayerAuctionData1.csv"
df = pd.read_csv(file_path)  
players = df.to_dict(orient="records")  

HOST = "0.0.0.0"
PORT = 5000
clients = []
current_bid = 0
current_player = None
highest_bidder = None
auction_running = False
auction_duration = 10

# Function to broadcast messages to all clients
def broadcast(message):
    disconnected_clients = []
    
    for client in clients:
        try:
            client.sendall(message.encode())
        except:
            disconnected_clients.append(client)
    
    for client in disconnected_clients:
        clients.remove(client)

# Handle incoming connections
def handle_client(client_socket, addr):
    global current_bid, highest_bidder

    logging.info(f"New connection from {addr}")
    clients.append(client_socket)

    while True:
        try:
            data = client_socket.recv(1024).decode()
            if not data:
                break

            bid_amount, bidder_name = data.split("|")
            bid_amount = float(bid_amount)

            if bid_amount <= 0:
                client_socket.sendall("Invalid bid amount. Please enter a positive value.".encode())
                continue  # Skip further processing

            if bid_amount > current_bid and auction_running:
                current_bid = bid_amount
                highest_bidder = bidder_name
                broadcast(f"New highest bid: {bid_amount} Cr by {bidder_name}")

        except Exception as e:
            logging.error(f"Error handling client {addr}: {e}")
            break

    logging.info(f"Client {addr} disconnected")
    clients.remove(client_socket)
    client_socket.close()

# Start auction for a player
def start_auction():
    global current_player, current_bid, highest_bidder, auction_running

    for player in players:
        current_player = player["Player Name"]
        base_price = player["Base Price"]
        current_bid = base_price
        highest_bidder = None
        auction_running = True

        logging.info(f"Auction started for {current_player} | Base Price: {base_price} Cr")
        broadcast(f"Auction started for {current_player} | Base Price: {base_price} Cr")

        # Countdown for bidding
        for i in range(auction_duration, 0, -1):
            broadcast(f"Time left: {i} sec | Highest Bid: {current_bid} Cr by {highest_bidder if highest_bidder else 'UNSOLD squad'}")
            time.sleep(1)

        # Auction closed
        auction_running = False
        winner_msg = f"Auction closed! {current_player} sold to {highest_bidder if highest_bidder else 'UNSOLD squad'} for {current_bid} Cr"
        logging.info(winner_msg)
        broadcast(winner_msg)
        time.sleep(2)

# Start the server (Step 2)
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen(5)
logging.info(f"Server started on {HOST}:{PORT}")

# Accepting client connections
threading.Thread(target=start_auction).start()

while True:
    client_socket, addr = server.accept()
    threading.Thread(target=handle_client, args=(client_socket, addr)).start()

