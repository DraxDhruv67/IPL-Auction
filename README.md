# 🏆 IPL Mega Auction 2025

Real-time multiplayer IPL auction system built with Flask + Socket.IO.

## 📁 Folder Structure

```
ipl_auction/
├── app.py                  ← Flask + SocketIO backend
├── requirements.txt        ← Python dependencies
├── data/
│   └── players.json        ← 30 IPL players dataset
├── static/
│   ├── css/style.css       ← Full IPL dark theme
│   └── js/main.js          ← Socket.IO client logic
└── templates/
    └── index.html          ← Single-page app UI
```

## 🚀 Quick Start

### 1. Install dependencies
```bash
cd ipl_auction
pip install -r requirements.txt
```

### 2. Run the server
```bash
python app.py
```

### 3. Open in browser
```
http://localhost:5000
```

## 🎮 How to Play

### Host
1. Enter your team name
2. Click **CREATE ROOM** — you get a 6-char room code
3. Share the code with friends
4. Click **START AUCTION** when everyone joins
5. Use **NEXT PLAYER** to advance after each result

### Players
1. Enter your team name
2. Enter the room code and click **JOIN**
3. Wait for host to start
4. Bid using **+₹10L / +₹50L / +₹100L (1Cr) / +₹200L (2Cr)** buttons
5. Each team starts with ₹100 Crore budget

## ⌨️ Keyboard Shortcuts (in auction)
| Key | Action |
|-----|--------|
| `1` | Bid +₹10L |
| `2` | Bid +₹50L |
| `3` | Bid +₹1 Cr |
| `4` | Bid +₹2 Cr |
| `n` | Next player (host only) |

## 📊 Player Dataset
30 real IPL players across roles: Batsman, Bowler, All-Rounder, Wicket-Keeper.
Base prices range from ₹1 Cr to ₹2 Cr.

To add Excel support:
```python
import openpyxl
# Load players from Excel
wb = openpyxl.load_workbook('players.xlsx')
ws = wb.active
players = [{'name': row[0], 'role': row[1], 'base_price': row[2]} for row in ws.iter_rows(min_row=2, values_only=True)]
```

## 🌐 Multiplayer Setup (LAN)
To play with people on the same network, run:
```bash
python app.py
```
Then share your local IP: `http://192.168.x.x:5000`

## 🔧 Tech Stack
- **Backend**: Python Flask + Flask-SocketIO (WebSockets)
- **Frontend**: HTML5, CSS3, Vanilla JavaScript
- **Real-time**: Socket.IO v4
- **Data**: JSON (Excel-ready with openpyxl)
