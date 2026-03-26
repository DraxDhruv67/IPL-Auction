# import eventlet
# eventlet.monkey_patch()
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room
import json, os, uuid, threading, time, random, hashlib

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ipl_auction_secret_2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ── Constants ──────────────────────────────────────────────────────────────────
rooms       = {}
sid_to_room = {}
sid_role    = {}   # sid -> 'bidder' | 'spectator'
color_pool  = ['#e63946','#2a9d8f','#e9c46a','#f4a261','#264653',
               '#8338ec','#3a86ff','#fb5607','#06d6a0','#118ab2']

INITIAL_BUDGET      = 10000
TIMER_SECONDS       = 20
MIN_TIMER_AFTER_BID = 10

# Bid increment rules: if current_bid >= threshold, min increment = step
BID_INCREMENT_RULES = [
    (0,    10),   # < 100L  → min +10L
    (100,  25),   # 100L–499L → min +25L
    (500,  50),   # 500L–999L → min +50L
    (1000, 100),  # 1Cr–4.99Cr → min +1Cr
    (500,  200),  # 5Cr+ → min +2Cr
]

# Granular sets: key = set_id, value = display label
ALL_SETS = {
    'bat_ind_cap':   'SET A1 — INDIAN CAPPED BATSMEN',
    'bat_ind_uncap': 'SET A2 — INDIAN UNCAPPED BATSMEN',
    'bat_foreign':   'SET A3 — FOREIGN BATSMEN',
    'wk_ind_cap':    'SET B1 — INDIAN CAPPED WICKET-KEEPERS',
    'wk_ind_uncap':  'SET B2 — INDIAN UNCAPPED WICKET-KEEPERS',
    'wk_foreign':    'SET B3 — FOREIGN WICKET-KEEPERS',
    'ar_ind_cap':    'SET C1 — INDIAN CAPPED ALL-ROUNDERS',
    'ar_ind_uncap':  'SET C2 — INDIAN UNCAPPED ALL-ROUNDERS',
    'ar_foreign':    'SET C3 — FOREIGN ALL-ROUNDERS',
    'bowl_ind_cap':  'SET D1 — INDIAN CAPPED BOWLERS',
    'bowl_ind_uncap':'SET D2 — INDIAN UNCAPPED BOWLERS',
    'bowl_foreign':  'SET D3 — FOREIGN BOWLERS',
}

def classify_player(p):
    """Return the set_id for a player based on role, nationality, capped status."""
    role = p.get('role','')
    nat  = p.get('nationality','India')
    cap  = p.get('capped', True)
    prefix = {
        'Batsman':'bat', 'Wicket-Keeper':'wk',
        'All-Rounder':'ar', 'Bowler':'bowl'
    }.get(role,'bat')
    if nat == 'India':
        suffix = 'ind_cap' if cap else 'ind_uncap'
    else:
        suffix = 'foreign'
    return f'{prefix}_{suffix}'

# Default order sets are auctioned in (real IPL style)
DEFAULT_SET_ORDER = [
    'bat_ind_cap','bat_foreign','bat_ind_uncap',
    'wk_ind_cap','wk_foreign','wk_ind_uncap',
    'ar_ind_cap','ar_foreign','ar_ind_uncap',
    'bowl_ind_cap','bowl_foreign','bowl_ind_uncap',
]

DATA_DIR   = os.path.join(os.path.dirname(__file__), 'data')
_tmp_users = os.path.join('/tmp', 'ipl_users.json')
USERS_FILE = _tmp_users if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('PORT') else os.path.join(DATA_DIR, 'users.json')

# ── User helpers ───────────────────────────────────────────────────────────────
def load_users():
    try:
        with open(USERS_FILE) as f: return json.load(f)
    except: return {}

def save_users(u):
    with open(USERS_FILE, 'w') as f: json.dump(u, f, indent=2)

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

# ── Player helpers ─────────────────────────────────────────────────────────────
def load_players():
    xlsx = os.path.join(DATA_DIR, 'ipl_players_2025.xlsx')
    if os.path.exists(xlsx):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(xlsx, data_only=True)
            ws = wb['Players']
            headers = [str(ws.cell(3,c).value).strip().lower()
                       .replace(' ','_').replace('(₹l)','').strip()
                       for c in range(1, ws.max_column+1)]
            players = []
            for row in ws.iter_rows(min_row=4, values_only=True):
                if not row[1]: continue
                p = dict(zip(headers, row))
                players.append({
                    'id':          p.get('#') or len(players)+1,
                    'name':        str(p.get('name','')).strip(),
                    'role':        str(p.get('role','')).strip(),
                    'nationality': str(p.get('nationality','India')).strip(),
                    'team':        str(p.get('ipl_franchise') or p.get('franchise','—')).strip(),
                    'base_price':  int(p.get('base_price') or p.get('base_price_') or 75),
                    'rating':      int(p.get('rating') or 70),
                })
            return players
        except Exception as e:
            print(f'Excel error: {e}')
    with open(os.path.join(DATA_DIR, 'players.json')) as f:
        return json.load(f)

def arrange_in_sets(players, selected_sets=None):
    """Group players into granular sets, respecting selected_sets filter."""
    order = selected_sets if selected_sets else DEFAULT_SET_ORDER
    # Only keep sets that actually exist in the order list
    order = [s for s in DEFAULT_SET_ORDER if s in order]
    buckets = {s: [] for s in order}
    for p in players:
        sid = classify_player(p)
        if sid in buckets:
            buckets[sid].append(p)
    result = []
    for set_id in order:
        group = buckets.get(set_id, [])
        if not group:
            continue
        random.shuffle(group)
        label = ALL_SETS.get(set_id, set_id)
        for i, p in enumerate(group):
            p['_set_id']    = set_id
            p['_set_label'] = label
            p['_set_start'] = (i == 0)
        result.extend(group)
    return result

def get_available_sets(players):
    """Return list of sets that have at least one player."""
    found = set()
    for p in players:
        found.add(classify_player(p))
    return [s for s in DEFAULT_SET_ORDER if s in found]

def get_min_increment(current_bid):
    """Return minimum allowed bid increment given current bid."""
    thresholds = [
        (5000, 500),
        (1000, 100),
        (500,   50),
        (100,   25),
        (0,     10),
    ]
    for threshold, increment in thresholds:
        if current_bid >= threshold:
            return increment
    return 10

# ── Room helpers ───────────────────────────────────────────────────────────────
def new_room(room_id, host_sid, host_name, selected_sets=None):
    raw = load_players()
    players = arrange_in_sets(raw, selected_sets)
    avail   = get_available_sets(raw)
    return {
        'id': room_id, 'host_sid': host_sid, 'host_name': host_name,
        'status': 'waiting', 'teams': {}, 'spectators': {},
        'players': players, 'player_index': -1,
        'all_players_pool': raw,           # full pool for injecting new sets mid-auction
        'available_sets': avail,           # all sets that exist in the data
        'active_sets': selected_sets or avail,
        'current_player': None, 'current_bid': 0,
        'current_bidder_sid': None, 'current_bidder_name': None,
        'timer': TIMER_SECONDS, 'timer_lock': threading.Lock(),
        'timer_stop': threading.Event(),
        'sold_players': [], 'unsold_players': [],
        'reauction_pool': [],
        'in_reauction': False,
        'set_vote': None,      # pending set-jump vote
        'reactions': [],
        'started_at': time.time(),
    }

def new_team(sid, name, idx):
    return {'sid': sid, 'name': name, 'budget': INITIAL_BUDGET,
            'players': [], 'color': color_pool[idx % len(color_pool)]}

def pub(room):
    idx = room['player_index']
    upcoming = room['players'][idx+1:idx+8] if not room['in_reauction'] else []
    # Compute which sets are still remaining (have players not yet auctioned)
    auctioned_names = {p['name'] for p in room['sold_players']+room['unsold_players']}
    remaining_sets = []
    for set_id in room.get('available_sets',[]):
        has_remaining = any(
            classify_player(p)==set_id and p['name'] not in auctioned_names
            for p in room.get('all_players_pool',[])
        )
        if has_remaining:
            remaining_sets.append({'id': set_id, 'label': ALL_SETS.get(set_id, set_id)})
    return {
        'id': room['id'], 'host_sid': room['host_sid'], 'host_name': room['host_name'],
        'status': room['status'], 'teams': list(room['teams'].values()),
        'spectator_count': len(room['spectators']),
        'current_player': room['current_player'],
        'current_bid': room['current_bid'],
        'current_bidder_sid': room['current_bidder_sid'],
        'current_bidder_name': room['current_bidder_name'],
        'timer': room['timer'],
        'players_left': max(0, len(room['players']) - idx - 1),
        'total_players': len(room['players']),
        'sold_count': len(room['sold_players']),
        'upcoming_players': upcoming,
        'unsold_count': len(room['unsold_players']),
        'reauction_remaining': len(room['reauction_pool']),
        'in_reauction': room['in_reauction'],
        'min_increment': get_min_increment(room['current_bid']),
        'reactions': room['reactions'][-20:],
        'remaining_sets': remaining_sets,
        'set_vote': room.get('set_vote'),
    }

# ── Timer ──────────────────────────────────────────────────────────────────────
def _timer_worker(room_id, stop_event):
    while not stop_event.is_set():
        time.sleep(1)
        if stop_event.is_set(): break
        room = rooms.get(room_id)
        if not room or room['status'] != 'bidding': break
        with room['timer_lock']:
            if room['status'] != 'bidding': break
            room['timer'] -= 1
            t = room['timer']
        socketio.emit('timer_tick', {'timer': t}, to=room_id)
        if t <= 0:
            _close_bid(room_id); break

def _start_timer(room):
    room['timer_stop'].set()
    stop = threading.Event()
    room['timer_stop'] = stop
    room['timer'] = TIMER_SECONDS
    threading.Thread(target=_timer_worker, args=(room['id'], stop), daemon=True).start()

def _close_bid(room_id):
    room = rooms.get(room_id)
    if not room or room['status'] != 'bidding': return
    player = room['current_player']
    if room['current_bidder_sid']:
        winner = room['teams'].get(room['current_bidder_sid'])
        if winner:
            winner['budget'] -= room['current_bid']
            winner['players'].append({**player, 'sold_price': room['current_bid']})
        room['sold_players'].append({
            **player, 'sold_price': room['current_bid'],
            'sold_to': room['current_bidder_name'],
            'sold_to_color': room['teams'].get(room['current_bidder_sid'],{}).get('color','#fff'),
        })
        room['status'] = 'sold'
        socketio.emit('player_sold', {
            'player': player, 'price': room['current_bid'],
            'team': room['current_bidder_name'],
            'color': room['teams'].get(room['current_bidder_sid'],{}).get('color','#fff'),
            'room': pub(room),
        }, to=room_id)
    else:
        room['unsold_players'].append(player)
        # add to re-auction pool automatically
        room['reauction_pool'].append(player)
        room['status'] = 'unsold'
        socketio.emit('player_unsold', {'player': player, 'room': pub(room)}, to=room_id)

def _finish_auction(room_id):
    room = rooms.get(room_id)
    if not room: return
    # If there are unsold players, offer re-auction instead of finishing
    if room['reauction_pool'] and not room['in_reauction']:
        room['status'] = 'reauction_pending'
        room['timer_stop'].set()
        socketio.emit('reauction_available', {
            'count': len(room['reauction_pool']),
            'players': [p['name'] for p in room['reauction_pool']],
            'room': pub(room),
        }, to=room_id)
        return
    room['status'] = 'finished'
    room['timer_stop'].set()
    _save_game_records(room)
    socketio.emit('auction_finished', {'room': pub(room), 'sold': room['sold_players']}, to=room_id)

def _save_game_records(room):
    users = load_users()
    changed = False
    for sid, team in room['teams'].items():
        username = team.get('username')
        if not username or username not in users: continue
        record = {
            'room_id': room['id'], 'date': time.strftime('%Y-%m-%d %H:%M'),
            'team_name': team['name'], 'budget_left': team['budget'],
            'players_won': len(team['players']),
            'total_spend': INITIAL_BUDGET - team['budget'],
            'squad': [{'name':p['name'],'role':p['role'],'price':p['sold_price']} for p in team['players']],
            'players_total': len(room['players']), 'sold_count': len(room['sold_players']),
        }
        users[username].setdefault('records', []).insert(0, record)
        users[username]['records'] = users[username]['records'][:20]
        changed = True
    if changed: save_users(users)

def _next_player(room_id):
    room = rooms.get(room_id)
    if not room: return
    if room['in_reauction']:
        if not room['reauction_pool']:
            # Re-auction done, finish for real
            room['in_reauction'] = False
            room['status'] = 'sold'
            _finish_auction_final(room_id)
            return
        player = room['reauction_pool'].pop(0)
    else:
        room['player_index'] += 1
        if room['player_index'] >= len(room['players']):
            _finish_auction(room_id); return
        player = room['players'][room['player_index']]
    room['current_player'] = player
    room['current_bid'] = player['base_price']
    room['current_bidder_sid'] = None
    room['current_bidder_name'] = None
    room['status'] = 'bidding'
    _start_timer(room)
    socketio.emit('new_player', {'player': player, 'room': pub(room)}, to=room_id)

def _finish_auction_final(room_id):
    room = rooms.get(room_id)
    if not room: return
    room['status'] = 'finished'
    room['timer_stop'].set()
    _save_game_records(room)
    socketio.emit('auction_finished', {'room': pub(room), 'sold': room['sold_players']}, to=room_id)

# ── HTTP ───────────────────────────────────────────────────────────────────────
@app.route('/')
def index(): return render_template('index.html')

@app.route('/api/rooms')
def api_rooms():
    return jsonify([
        {'id': r['id'], 'host': r['host_name'], 'teams': len(r['teams']),
         'spectators': len(r['spectators']), 'status': r['status']}
        for r in rooms.values() if r['status'] != 'finished'
    ])

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip().lower()
    password = (data.get('password') or '').strip()
    display  = (data.get('display') or username).strip()[:20]
    if not username or not password:
        return jsonify({'ok': False, 'msg': 'Username and password required'}), 400
    if len(username) < 3:
        return jsonify({'ok': False, 'msg': 'Username must be at least 3 characters'}), 400
    users = load_users()
    if username in users:
        return jsonify({'ok': False, 'msg': 'Username already taken'}), 409
    users[username] = {'username': username, 'display': display,
                       'password': hash_pw(password), 'created': time.strftime('%Y-%m-%d'), 'records': []}
    save_users(users)
    return jsonify({'ok': True, 'user': {'username': username, 'display': display}})

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip().lower()
    password = (data.get('password') or '').strip()
    users = load_users()
    u = users.get(username)
    if not u or u['password'] != hash_pw(password):
        return jsonify({'ok': False, 'msg': 'Invalid username or password'}), 401
    return jsonify({'ok': True, 'user': {'username': username, 'display': u.get('display', username)}})

@app.route('/api/profile/<username>')
def get_profile(username):
    users = load_users()
    u = users.get(username.lower())
    if not u: return jsonify({'ok': False, 'msg': 'User not found'}), 404
    return jsonify({'ok': True, 'display': u.get('display', username),
                    'created': u.get('created',''), 'records': u.get('records',[])})

# ── Socket events ──────────────────────────────────────────────────────────────
@socketio.on('connect')
def on_connect(): emit('connected', {'sid': request.sid})

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    room_id = sid_to_room.pop(sid, None)
    if not room_id: return
    role = sid_role.pop(sid, 'bidder')
    room = rooms.get(room_id)
    if not room: return
    if role == 'spectator':
        name = room['spectators'].pop(sid, {}).get('name','?')
        socketio.emit('notification', {'msg': f'👁 {name} stopped watching'}, to=room_id)
    else:
        leaving = room['teams'].pop(sid, {})
        name = leaving.get('name', '?')
        if room['current_bidder_sid'] == sid:
            room['current_bidder_sid'] = None; room['current_bidder_name'] = None
        if not room['teams']:
            room['timer_stop'].set(); rooms.pop(room_id, None); return
        socketio.emit('notification', {'msg': f'👋 {name} left'}, to=room_id)
    socketio.emit('room_update', pub(room), to=room_id)

@socketio.on('create_room')
def on_create_room(data):
    sid  = request.sid
    name = (data.get('name') or 'Host').strip()[:20]
    username = data.get('username','')
    selected_sets = data.get('selected_sets', None)  # granular set selection
    room_id = str(uuid.uuid4())[:6].upper()
    room = new_room(room_id, sid, name, selected_sets)
    team = new_team(sid, name, 0)
    if username: team['username'] = username
    room['teams'][sid] = team
    rooms[room_id] = room; sid_to_room[sid] = room_id; sid_role[sid] = 'bidder'
    join_room(room_id)
    emit('room_joined', {'room': pub(room), 'your_sid': sid, 'room_id': room_id, 'role': 'bidder'})

@socketio.on('join_room_req')
def on_join_room(data):
    sid     = request.sid
    room_id = (data.get('room_id') or '').strip().upper()
    name    = (data.get('name') or 'Team').strip()[:20]
    username = data.get('username','')
    as_spectator = data.get('spectator', False)
    room = rooms.get(room_id)
    if not room:
        emit('error', {'msg': f'Room "{room_id}" not found.'}); return
    if room['status'] == 'finished':
        emit('error', {'msg': 'This auction has ended.'}); return
    sid_to_room[sid] = room_id
    join_room(room_id)
    if as_spectator:
        room['spectators'][sid] = {'name': name, 'sid': sid}
        sid_role[sid] = 'spectator'
        emit('room_joined', {'room': pub(room), 'your_sid': sid, 'room_id': room_id, 'role': 'spectator'})
        socketio.emit('notification', {'msg': f'👁 {name} is watching'}, to=room_id)
    else:
        idx  = len(room['teams'])
        team = new_team(sid, name, idx)
        if username: team['username'] = username
        room['teams'][sid] = team
        sid_role[sid] = 'bidder'
        emit('room_joined', {'room': pub(room), 'your_sid': sid, 'room_id': room_id, 'role': 'bidder'})
        socketio.emit('notification', {'msg': f'🏏 {name} joined!'}, to=room_id)
    socketio.emit('room_update', pub(room), to=room_id)

@socketio.on('start_auction')
def on_start(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room: emit('error',{'msg':'Not in a room.'}); return
    if room['host_sid'] != sid: emit('error',{'msg':'Only the host can start.'}); return
    if room['status'] != 'waiting': emit('error',{'msg':'Auction already started.'}); return
    _next_player(room_id)

@socketio.on('next_player')
def on_next(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    if room['status'] not in ('sold','unsold','waiting'):
        emit('error',{'msg':'Cannot proceed right now.'}); return
    _next_player(room_id)

@socketio.on('skip_player')
def on_skip(data):
    """Host sends current player to unsold immediately."""
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    if room['status'] != 'bidding': return
    room['timer_stop'].set()
    room['status'] = 'bidding'   # allow _close_bid to run
    player = room['current_player']
    room['unsold_players'].append(player)
    room['reauction_pool'].append(player)
    room['status'] = 'unsold'
    socketio.emit('player_unsold', {'player': player, 'room': pub(room)}, to=room_id)

@socketio.on('start_reauction')
def on_start_reauction(data):
    """Host confirms starting the re-auction round."""
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    if room['status'] != 'reauction_pending': return
    room['in_reauction'] = True
    room['status'] = 'waiting'
    socketio.emit('reauction_started', {'room': pub(room)}, to=room_id)
    _next_player(room_id)

@socketio.on('skip_reauction')
def on_skip_reauction(data):
    """Host skips re-auction, go straight to results."""
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    room['reauction_pool'] = []
    _finish_auction_final(room_id)

@socketio.on('stop_auction')
def on_stop(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    if room['status'] == 'finished': return
    room['timer_stop'].set()
    room['reauction_pool'] = []   # skip re-auction when manually stopping
    _finish_auction_final(room_id)

@socketio.on('place_bid')
def on_bid(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['status'] != 'bidding': return
    if sid_role.get(sid) == 'spectator':
        emit('error',{'msg':"Spectators can't bid!"}); return
    team = room['teams'].get(sid)
    if not team: return
    try: amount = int(data.get('amount', 0))
    except: return
    if amount <= 0: return
    # Bid increment lock
    min_inc = get_min_increment(room['current_bid'])
    if amount < min_inc:
        emit('error',{'msg':f'Minimum bid increment is ₹{min_inc}L at this price!'}); return
    new_bid = room['current_bid'] + amount
    if new_bid > team['budget']:
        emit('error',{'msg':f'Not enough budget!'}); return
    if sid == room['current_bidder_sid']:
        emit('error',{'msg':"You're already highest bidder!"}); return
    with room['timer_lock']:
        room['current_bid'] = new_bid
        room['current_bidder_sid'] = sid
        room['current_bidder_name'] = team['name']
        room['timer'] = max(room['timer'], MIN_TIMER_AFTER_BID)
    socketio.emit('bid_update', {
        'bid': new_bid, 'bidder': team['name'],
        'bidder_color': team['color'], 'bidder_sid': sid,
        'timer': room['timer'], 'room': pub(room),
    }, to=room_id)

@socketio.on('send_reaction')
def on_reaction(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room: return
    emoji = data.get('emoji','🔥')
    allowed = ['🔥','😱','💰','👏','😂','🏏','⚡','💎']
    if emoji not in allowed: return
    # get name from team or spectator
    name = room['teams'].get(sid,{}).get('name') or room['spectators'].get(sid,{}).get('name','?')
    reaction = {'emoji': emoji, 'name': name, 'ts': time.time()}
    room['reactions'].append(reaction)
    socketio.emit('reaction', reaction, to=room_id)

@socketio.on('propose_set_jump')
def on_propose_set_jump(data):
    """Any player proposes jumping to a different set. Host sees a confirm dialog."""
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['status'] not in ('bidding','sold','unsold'): return
    if sid_role.get(sid) == 'spectator': return
    set_id = data.get('set_id','')
    if set_id not in ALL_SETS: return
    # Check set exists and has unseen players
    auctioned = {p['name'] for p in room['sold_players']+room['unsold_players']}
    has_players = any(
        classify_player(p)==set_id and p['name'] not in auctioned
        for p in room.get('all_players_pool',[])
    )
    if not has_players:
        emit('error', {'msg': 'No remaining players in that set!'}); return
    proposer = room['teams'].get(sid,{}).get('name','?')
    vote = {'set_id': set_id, 'label': ALL_SETS[set_id], 'proposer': proposer, 'sid': sid}
    room['set_vote'] = vote
    socketio.emit('set_jump_proposed', {'vote': vote, 'room': pub(room)}, to=room_id)

@socketio.on('confirm_set_jump')
def on_confirm_set_jump(data):
    """Host confirms the set jump — inject that set's players next."""
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    vote = room.get('set_vote')
    if not vote: return
    set_id = vote['set_id']
    auctioned = {p['name'] for p in room['sold_players']+room['unsold_players']}
    # Collect unseen players from the requested set
    new_players = [
        dict(p, _set_id=set_id, _set_label=ALL_SETS[set_id], _set_start=False)
        for p in room['all_players_pool']
        if classify_player(p)==set_id and p['name'] not in auctioned
    ]
    if not new_players:
        emit('error', {'msg': 'No players left in that set!'}); return
    random.shuffle(new_players)
    new_players[0]['_set_start'] = True
    # Insert new set players right after current position
    idx = room['player_index']
    room['players'] = room['players'][:idx+1] + new_players + room['players'][idx+1:]
    room['set_vote'] = None
    socketio.emit('set_jump_confirmed', {
        'set_label': ALL_SETS[set_id],
        'count': len(new_players),
        'room': pub(room)
    }, to=room_id)

@socketio.on('reject_set_jump')
def on_reject_set_jump(data):
    """Host rejects the set jump proposal."""
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    room['set_vote'] = None
    socketio.emit('set_jump_rejected', {'room': pub(room)}, to=room_id)

@socketio.on('get_state')
def on_get_state(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if room: emit('full_state', pub(room))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, use_reloader=False)
