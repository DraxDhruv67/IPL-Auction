import socket
import threading
import tkinter as tk
from tkinter import messagebox

# Server details
SERVER_IP = "127.0.0.2"  # Change this if server runs on another device
PORT = 5000

# Create client socket
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((SERVER_IP, PORT))

# GUI App Class
class AuctionClient:
    def __init__(self, root):
        self.root = root
        self.root.title("IPL Auction - Bidder")
        self.root.geometry("400x300")

        # Player Name Display
        self.player_label = tk.Label(root, text="Waiting for auction...", font=("Arial", 14))
        self.player_label.pack(pady=10)

        # Current Bid Display
        self.bid_label = tk.Label(root, text="Highest Bid: -- Cr for {player name}", font=("Arial", 12))
        self.bid_label.pack(pady=5)

        # Bid Entry
        self.bid_entry = tk.Entry(root, font=("Arial", 12))
        self.bid_entry.pack(pady=5)

        # Bidder Name Entry
        self.name_entry = tk.Entry(root, font=("Arial", 12))
        self.name_entry.pack(pady=5)
        self.name_entry.insert(0, "Your Name")

        # Submit Bid Button
        self.bid_button = tk.Button(root, text="Place Bid", command=self.place_bid, font=("Arial", 12))
        self.bid_button.pack(pady=10)

        # Live Updates
        self.update_thread = threading.Thread(target=self.receive_updates, daemon=True)
        self.update_thread.start()

    def place_bid(self):
        """Send bid to the server"""
        bid = self.bid_entry.get().strip()
        name = self.name_entry.get().strip()

        if not bid or not name:
            messagebox.showwarning("Invalid Input", "Please enter a valid bid and name!")
            return

        try:
            bid_value = float(bid)
            if bid_value <= 0:
                messagebox.showwarning("Invalid Bid", "Bid must be greater than zero!")
                return
            client.sendall(f"{bid}|{name}".encode())
        except ValueError:
            messagebox.showwarning("Invalid Bid", "Enter a numeric bid amount!")

    def receive_updates(self):
        """Receive and update auction status"""
        while True:
            try:
                message = client.recv(1024).decode()
                if "Auction started for" in message:
                    self.player_label.config(text=message)
                elif "Highest Bid" in message:
                    self.bid_label.config(text=message)
                elif "Auction closed!" in message:
                    messagebox.showinfo("Auction Result", message)
            except:
                break  # Connection closed

# Run GUI
root = tk.Tk()
app = AuctionClient(root)
root.mainloop()
