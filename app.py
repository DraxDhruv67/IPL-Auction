import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room
import json, os, uuid, time, random, hashlib

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ipl_auction_secret_2024')
async_mode = 'threading' if os.name == 'nt' and 'PORT' not in os.environ else 'eventlet'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode=async_mode)

# ── State ──────────────────────────────────────────────────────────────────────
rooms       = {}
sid_to_room = {}
sid_role    = {}
color_pool  = ['#e63946','#2a9d8f','#e9c46a','#f4a261','#264653',
               '#8338ec','#3a86ff','#fb5607','#06d6a0','#118ab2']

INITIAL_BUDGET      = 10000
TIMER_SECONDS       = 20
MIN_TIMER_AFTER_BID = 10

# Bot personality configs
BOT_NAMES = [
    ('RCB Bot',  '#e63946', 'aggressive'),
    ('MI Bot',   '#0047CC', 'smart'),
    ('CSK Bot',  '#e9c46a', 'conservative'),
    ('KKR Bot',  '#8338ec', 'random'),
    ('SRH Bot',  '#fb5607', 'aggressive'),
    ('GT Bot',   '#06d6a0', 'smart'),
]

ALL_SETS = {
    'unsold':        'SET X — UNSOLD PLAYERS',
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
DEFAULT_SET_ORDER = [
    'bat_ind_cap','bat_foreign','bat_ind_uncap',
    'wk_ind_cap','wk_foreign','wk_ind_uncap',
    'ar_ind_cap','ar_foreign','ar_ind_uncap',
    'bowl_ind_cap','bowl_foreign','bowl_ind_uncap',
]

DATA_DIR   = os.path.join(os.path.dirname(__file__), 'data')
_tmp_users = os.path.join('/tmp', 'ipl_users.json')
PRIMARY_USERS_FILE = os.path.join(DATA_DIR, 'users.json')

# ── User helpers ───────────────────────────────────────────────────────────────
def load_users():
    for fpath in [PRIMARY_USERS_FILE, _tmp_users]:
        try:
            if os.path.exists(fpath):
                with open(fpath, 'r', encoding='utf-8') as f:
                    u = json.load(f)
                    if u: return u
        except Exception as e:
            print(f"Error reading users from {fpath}: {e}")
    return {}

def save_users(u):
    # Try primary file first (inside container / app dir)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(PRIMARY_USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(u, f, indent=2)
            return
    except Exception as e:
        print(f"Cannot save users to {PRIMARY_USERS_FILE}: {e}")
    # Fallback to /tmp if primary path is read-only
    try:
        with open(_tmp_users, 'w', encoding='utf-8') as f:
            json.dump(u, f, indent=2)
    except Exception as e:
        print(f"Cannot save users to {_tmp_users}: {e}")

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
                    'capped':      bool(p.get('capped', True)),
                    'team':        str(p.get('ipl_franchise') or p.get('franchise','—')).strip(),
                    'base_price':  int(p.get('base_price') or p.get('base_price_') or 75),
                    'rating':      int(p.get('rating') or 70),
                })
            return players
        except Exception as e:
            print(f'Excel error: {e}')
    with open(os.path.join(DATA_DIR, 'players.json')) as f:
        return json.load(f)

def classify_player(p):
    role = p.get('role','')
    nat  = p.get('nationality','India')
    cap  = p.get('capped', True)
    prefix = {'Batsman':'bat','Wicket-Keeper':'wk','All-Rounder':'ar','Bowler':'bowl'}.get(role,'bat')
    suffix = ('ind_cap' if cap else 'ind_uncap') if nat == 'India' else 'foreign'
    return f'{prefix}_{suffix}'

def arrange_in_sets(players, selected_sets=None):
    order = [s for s in DEFAULT_SET_ORDER if not selected_sets or s in selected_sets]
    buckets = {s: [] for s in order}
    for p in players:
        sid = classify_player(p)
        if sid in buckets:
            buckets[sid].append(p)
    result = []
    for set_id in order:
        group = buckets.get(set_id, [])
        if not group: continue
        random.shuffle(group)
        label = ALL_SETS.get(set_id, set_id)
        for i, p in enumerate(group):
            p = dict(p)  # copy so original pool is not mutated
            p['_set_id']    = set_id
            p['_set_label'] = label
            p['_set_start'] = (i == 0)
            group[i] = p
        result.extend(group)
    return result

def get_min_increment(current_bid):
    for threshold, inc in [(5000,500),(1000,100),(500,50),(100,25),(0,10)]:
        if current_bid >= threshold: return inc
    return 10

def snap_bid(current_bid, button_amount):
    """Snap bid to next clean multiple above current_bid + button_amount.
    Prevents 50L button at ₹1.8Cr giving ₹2.3Cr instead of ₹2.5Cr."""
    raw = current_bid + button_amount
    # Determine the rounding grid at this price level
    if raw >= 5000:  grid = 500
    elif raw >= 1000: grid = 100
    elif raw >= 500:  grid = 50
    elif raw >= 100:  grid = 25
    else:             grid = 10
    # Round UP to next grid boundary
    remainder = raw % grid
    return raw if remainder == 0 else raw + (grid - remainder)

# ── Room helpers ───────────────────────────────────────────────────────────────
def new_room(room_id, host_sid, host_name, selected_sets=None):
    raw = load_players()
    players = arrange_in_sets(raw, selected_sets)
    avail = list({classify_player(p) for p in raw} & set(DEFAULT_SET_ORDER))
    avail.sort(key=DEFAULT_SET_ORDER.index)
    return {
        'id': room_id, 'host_sid': host_sid, 'host_name': host_name,
        'status': 'waiting', 'teams': {}, 'spectators': {},
        'players': players, 'player_index': -1,
        'raw_players': raw,
        'available_sets': avail,
        'current_player': None, 'current_bid': 0,
        'current_bidder_sid': None, 'current_bidder_name': None,
        'timer': TIMER_SECONDS,
        # FIX: use a simple integer counter instead of threading.Lock under eventlet
        'player_version': 0,   # incremented on new_player/skip -> kills timer greenlet
        'bid_version': 0,      # incremented on every bid -> guards _close_bid from double-fire
        'sold_players': [], 'unsold_players': [],
        'reauction_pool': [], 'in_reauction': False,
        'set_vote': None, 'reactions': [],
        'started_at': time.time(),
        'bots': {},
        # Skip vote: tracks who has voted to skip current player
        'skip_votes': set(),      # set of sids who voted to skip
        'skip_vote_active': False,
    }

def new_team(sid, name, idx, is_bot=False):
    t = {'sid': sid, 'name': name, 'budget': INITIAL_BUDGET,
         'players': [], 'color': color_pool[idx % len(color_pool)], 'is_bot': is_bot}
    return t

def pub(room):
    idx = room['player_index']
    upcoming = room['players'][idx+1:idx+8] if not room['in_reauction'] else []
    # Efficient remaining-sets calc using player queue (not raw_players scan)
    auctioned = {p['name'] for p in room['sold_players']+room['unsold_players']}
    seen_sets  = set()
    remaining_sets = []
    for p in room['players'][idx+1:]:
        sid = p.get('_set_id') or classify_player(p)
        if sid not in seen_sets:
            seen_sets.add(sid)
            if p['name'] not in auctioned:
                remaining_sets.append({'id': sid, 'label': ALL_SETS.get(sid, sid)})
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
        'skip_vote_active': room.get('skip_vote_active', False),
        'skip_votes': len(room.get('skip_votes', set())),
        'skip_votes_needed': max(1, len([t for t in room['teams'].values() if not t.get('is_bot')])),
    }

# ── Timer — eventlet-safe, no threading.Lock ─────────────────────────────────
def _start_timer(room):
    """Start a greenlet-based countdown. Uses bid_version to detect stale timers."""
    room['timer'] = TIMER_SECONDS
    room_id  = room['id']
    player_ver = room['player_version']  # only player_version kills the timer

    def _run():
        while True:
            eventlet.sleep(1)
            r = rooms.get(room_id)
            if not r or r['player_version'] != player_ver or r['status'] != 'bidding':
                return  # new player started or room gone
            r['timer'] = max(0, r['timer'] - 1)
            socketio.emit('timer_tick', {'timer': r['timer']}, to=room_id)
            if r['timer'] <= 0:
                _close_bid(room_id, r['bid_version'])
                return

    eventlet.spawn(_run)

# ── Bid close ─────────────────────────────────────────────────────────────────
def _close_bid(room_id, expected_bid_version=None):
    """Close current bid. expected_bid_version prevents double-close race."""
    room = rooms.get(room_id)
    if not room or room['status'] != 'bidding': return
    if expected_bid_version is not None and room['bid_version'] != expected_bid_version:
        return  # another bid landed between timer hitting 0 and this call
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
        # Auto-advance after 5s if host doesn't click Next
        cap_ver = room['player_version']
        eventlet.spawn_after(5, _auto_next, room_id, cap_ver)
    else:
        unsold_tagged = dict(player,
            _set_id='unsold',
            _set_label='SET X — UNSOLD PLAYERS',
            _set_start=False)
        room['unsold_players'].append(player)
        room['reauction_pool'].append(unsold_tagged)
        room['status'] = 'unsold'
        socketio.emit('player_unsold', {'player': player, 'room': pub(room)}, to=room_id)
        cap_ver = room['player_version']
        eventlet.spawn_after(5, _auto_next, room_id, cap_ver)

def _auto_next(room_id, expected_player_ver):
    """Auto-advance to next player if host hasn't clicked Next within 5s."""
    room = rooms.get(room_id)
    if not room: return
    if room['player_version'] != expected_player_ver: return  # host already clicked next
    if room['status'] not in ('sold', 'unsold'): return
    _next_player(room_id)

def _finish_auction(room_id):
    room = rooms.get(room_id)
    if not room: return
    if room['reauction_pool'] and not room['in_reauction']:
        # Mark first unsold player as set_start so header shows
        pool = room['reauction_pool']
        pool[0] = dict(pool[0], _set_start=True)
        room['status'] = 'reauction_pending'
        socketio.emit('reauction_available', {
            'count': len(pool),
            'players': [p['name'] for p in pool],
            'room': pub(room),
        }, to=room_id)
        return
    _finish_auction_final(room_id)

def _finish_auction_final(room_id):
    room = rooms.get(room_id)
    if not room: return
    room['status'] = 'finished'
    _save_game_records(room)
    socketio.emit('auction_finished', {'room': pub(room), 'sold': room['sold_players']}, to=room_id)

def _save_game_records(room):
    users = load_users(); changed = False
    for sid, team in room['teams'].items():
        if team.get('is_bot'): continue
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
            room['in_reauction'] = False
            _finish_auction_final(room_id); return
        player = room['reauction_pool'].pop(0)
    else:
        room['player_index'] += 1
        if room['player_index'] >= len(room['players']):
            _finish_auction(room_id); return
        player = room['players'][room['player_index']]
    room['current_player']      = player
    room['current_bid']         = player['base_price']
    room['current_bidder_sid']  = None
    room['current_bidder_name'] = None
    room['status']              = 'bidding'
    room['player_version']     += 1
    room['bid_version']         = 0
    room['skip_votes']          = set()      # reset skip votes for new player
    room['skip_vote_active']    = False
    _start_timer(room)
    socketio.emit('new_player', {'player': player, 'room': pub(room)}, to=room_id)
    # Schedule bot bids after a short delay
    eventlet.spawn_after(2, _bot_consider_bid, room_id, room['player_version'])

# ── Bot AI ────────────────────────────────────────────────────────────────────
# Bots use a multi-factor valuation model:
#   - player rating (quality signal)
#   - squad need (does bot need this role?)
#   - budget pressure (how much budget is left vs players needed)
#   - competition (how many other teams are bidding)
#   - personality style (aggressive/smart/conservative/random)

def _bot_value_player(bot_sid, room):
    """Multi-factor valuation: rating × need × budget × style."""
    team   = room['teams'].get(bot_sid, {})
    bot    = room['bots'].get(bot_sid, {})
    player = room['current_player']
    style  = bot.get('style', 'smart')
    budget = team['budget']
    if budget <= 0: return 0

    base   = player.get('base_price', 75)
    rating = player.get('rating', 70)
    role   = player.get('role', 'Batsman')

    # 1. Rating factor: 70=1.0x, 80=1.5x, 90=2.0x
    rating_factor = 1.0 + max(0, rating - 70) / 20.0

    # 2. Squad need
    squad  = team.get('players', [])
    counts = {}
    for p in squad:
        counts[p.get('role','')] = counts.get(p.get('role',''), 0) + 1
    targets = {'Batsman':4,'Bowler':4,'All-Rounder':2,'Wicket-Keeper':1}
    have = counts.get(role, 0)
    need = targets.get(role, 2)
    if   have == 0:           need_factor = 1.4   # desperately need this role
    elif have < need:         need_factor = 1.15
    elif have == need:        need_factor = 0.9
    else:                     need_factor = 0.65  # overstocked

    # 3. Budget: don't spend more than 40% of remaining on one player (smart/conservative)
    #    Aggressive bots ignore this cap
    budget_cap = budget * (0.5 if style=='aggressive' else 0.4 if style=='smart' else 0.3)

    # 4. Style multiplier (randomised per auction to feel natural)
    seed = bot.get('seed', random.random())  # stable per bot instance
    if style == 'aggressive':
        style_mult = 1.5 + seed * 0.3        # 1.5–1.8
    elif style == 'smart':
        style_mult = 1.1 + seed * 0.25       # 1.1–1.35
    elif style == 'conservative':
        style_mult = 0.8 + seed * 0.2        # 0.8–1.0
    else:  # random
        style_mult = 0.9 + random.random() * 1.0  # 0.9–1.9 (re-rolled each time)

    max_pay = int(base * rating_factor * need_factor * style_mult)
    # Apply hard budget cap
    max_pay = min(max_pay, budget_cap, budget)
    # Must at least be willing to pay base price if needed
    if need_factor >= 1.15:
        max_pay = max(max_pay, min(base, budget))
    return int(max_pay)

def _bot_consider_bid(room_id, player_ver):
    """Wake all bots to independently decide whether to bid."""
    room = rooms.get(room_id)
    if not room or room['status'] != 'bidding': return
    if room['player_version'] != player_ver: return
    for bot_sid in list(room['bots'].keys()):
        team = room['teams'].get(bot_sid)
        if not team: continue
        delay = random.uniform(0.5, 2.5)  # faster: was 0.8–3.5
        eventlet.spawn_after(delay, _bot_bid_attempt, room_id, bot_sid, player_ver)

def _bot_bid_attempt(room_id, bot_sid, player_ver):
    """Single bot decides whether to bid right now."""
    room = rooms.get(room_id)
    if not room or room['status'] != 'bidding': return
    if room['player_version'] != player_ver: return
    team = room['teams'].get(bot_sid)
    bot  = room['bots'].get(bot_sid)
    if not team or not bot: return
    if bot_sid == room['current_bidder_sid']: return

    cur_bid = room['current_bid']
    max_pay = _bot_value_player(bot_sid, room)

    if cur_bid >= max_pay: return
    inc = get_min_increment(cur_bid)
    if team['budget'] < cur_bid + inc: return

    new_bid = snap_bid(cur_bid, inc)
    if new_bid > team['budget']: return

    room['current_bid']         = new_bid
    room['current_bidder_sid']  = bot_sid
    room['current_bidder_name'] = team['name']
    room['timer']               = max(room['timer'], MIN_TIMER_AFTER_BID)
    room['bid_version']        += 1

    socketio.emit('bid_update', {
        'bid': new_bid, 'bidder': team['name'],
        'bidder_color': team['color'], 'bidder_sid': bot_sid,
        'timer': room['timer'], 'room': pub(room),
    }, to=room_id)

    # Other bots re-evaluate quickly after a bid
    eventlet.spawn_after(random.uniform(1.0, 3.0), _bot_consider_bid, room_id, player_ver)

# ── HTTP ───────────────────────────────────────────────────────────────────────
@app.route('/')
def index(): return render_template('index.html')

@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

@app.route('/sw.js')
def service_worker():
    response = app.send_static_file('sw.js')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Content-Type'] = 'application/javascript'
    return response

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
        real_teams = [t for t in room['teams'].values() if not t.get('is_bot')]
        if not real_teams:
            rooms.pop(room_id, None); return
        socketio.emit('notification', {'msg': f'👋 {name} left'}, to=room_id)
    socketio.emit('room_update', pub(room), to=room_id)

@socketio.on('create_room')
def on_create_room(data):
    sid  = request.sid
    name = (data.get('name') or 'Host').strip()[:20]
    username = data.get('username','')
    selected_sets = data.get('selected_sets', None)
    bot_count = min(int(data.get('bots', 0)), 5)
    room_id = str(uuid.uuid4())[:6].upper()
    room = new_room(room_id, sid, name, selected_sets)
    team = new_team(sid, name, 0)
    if username: team['username'] = username
    room['teams'][sid] = team
    # Add bots
    for i in range(bot_count):
        bot_cfg = BOT_NAMES[i % len(BOT_NAMES)]
        bot_sid = f'bot_{room_id}_{i}'
        bteam = new_team(bot_sid, bot_cfg[0], i+1, is_bot=True)
        bteam['color'] = bot_cfg[1]
        room['teams'][bot_sid] = bteam
        room['bots'][bot_sid]  = {'style': bot_cfg[2], 'seed': random.random()}
        sid_role[bot_sid] = 'bidder'
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
    sid_to_room[sid] = room_id; join_room(room_id)
    if as_spectator:
        room['spectators'][sid] = {'name': name, 'sid': sid}
        sid_role[sid] = 'spectator'
        emit('room_joined', {'room': pub(room), 'your_sid': sid, 'room_id': room_id, 'role': 'spectator'})
        socketio.emit('notification', {'msg': f'👁 {name} is watching'}, to=room_id)
    else:
        idx  = len(room['teams'])
        team = new_team(sid, name, idx)
        if username: team['username'] = username
        room['teams'][sid] = team; sid_role[sid] = 'bidder'
        emit('room_joined', {'room': pub(room), 'your_sid': sid, 'room_id': room_id, 'role': 'bidder'})
        socketio.emit('notification', {'msg': f'🏏 {name} joined!'}, to=room_id)
    socketio.emit('room_update', pub(room), to=room_id)

@socketio.on('start_auction')
def on_start(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room: emit('error',{'msg':'Not in a room.'}); return
    if room['host_sid'] != sid: emit('error',{'msg':'Only the host can start.'}); return
    if room['status'] != 'waiting': emit('error',{'msg':'Already started.'}); return
    _next_player(room_id)

@socketio.on('next_player')
def on_next(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    if room['status'] not in ('sold','unsold','waiting'):
        emit('error',{'msg':'Cannot proceed right now.'}); return
    _next_player(room_id)

@socketio.on('vote_skip')
def on_vote_skip(data):
    """Any bidder votes to skip current player. When all human teams vote, player is skipped."""
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['status'] != 'bidding': return
    if sid_role.get(sid) == 'spectator': return
    if room['teams'].get(sid, {}).get('is_bot'): return
    # Host can force-skip immediately without waiting for all votes
    if sid == room['host_sid']:
        _do_skip(room_id); return
    room['skip_votes'].add(sid)
    room['skip_vote_active'] = True
    human_teams = [t for t in room['teams'].values() if not t.get('is_bot')]
    votes_needed = len(human_teams)
    votes_cast   = len(room['skip_votes'])
    socketio.emit('skip_vote_update', {
        'votes': votes_cast, 'needed': votes_needed,
        'voter': room['teams'].get(sid, {}).get('name', '?'),
        'room': pub(room),
    }, to=room_id)
    if votes_cast >= votes_needed:
        _do_skip(room_id)

@socketio.on('retract_skip')
def on_retract_skip(data):
    """Bidder retracts their skip vote."""
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room: return
    room['skip_votes'].discard(sid)
    if not room['skip_votes']:
        room['skip_vote_active'] = False
    socketio.emit('skip_vote_update', {
        'votes': len(room['skip_votes']),
        'needed': max(1, len([t for t in room['teams'].values() if not t.get('is_bot')])),
        'voter': None, 'room': pub(room),
    }, to=room_id)

def _do_skip(room_id):
    """Actually skip current player — move to unsold set."""
    room = rooms.get(room_id)
    if not room or room['status'] != 'bidding': return
    player = room['current_player']
    room['player_version'] += 1
    room['bid_version']    += 1
    room['skip_votes']      = set()
    room['skip_vote_active'] = False
    room['status'] = 'unsold'
    # Add to unsold_players for record
    room['unsold_players'].append(player)
    # Tag player as part of unsold set and add to reauction_pool
    unsold_player = dict(player, _set_id='unsold', _set_label='SET X — UNSOLD PLAYERS', _set_start=False)
    room['reauction_pool'].append(unsold_player)
    socketio.emit('player_skipped', {
        'player': player,
        'room': pub(room),
        'msg': f"{player['name']} moved to Unsold Players set",
    }, to=room_id)

@socketio.on('start_reauction')
def on_start_reauction(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    if room['status'] != 'reauction_pending': return
    room['in_reauction'] = True; room['status'] = 'waiting'
    socketio.emit('reauction_started', {'room': pub(room)}, to=room_id)
    _next_player(room_id)

@socketio.on('skip_reauction')
def on_skip_reauction(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    room['reauction_pool'] = []
    _finish_auction_final(room_id)

@socketio.on('stop_auction')
def on_stop(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    if room['status'] == 'finished': return
    room['player_version'] += 1
    room['bid_version']    += 1
    room['reauction_pool'] = []
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
    cur = room['current_bid']
    new_bid = cur + amount
    if new_bid > team['budget']:
        emit('error',{'msg':'Not enough budget!'}); return
    if sid == room['current_bidder_sid']:
        emit('error',{'msg':"You're already highest bidder!"}); return
    room['current_bid']         = new_bid
    room['current_bidder_sid']  = sid
    room['current_bidder_name'] = team['name']
    room['timer']               = max(room['timer'], MIN_TIMER_AFTER_BID)
    room['bid_version']        += 1
    socketio.emit('bid_update', {
        'bid': new_bid, 'bidder': team['name'],
        'bidder_color': team['color'], 'bidder_sid': sid,
        'timer': room['timer'], 'room': pub(room),
    }, to=room_id)
    eventlet.spawn_after(random.uniform(1.5, 4.0), _bot_consider_bid, room_id, room['player_version'])

@socketio.on('send_reaction')
def on_reaction(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room: return
    emoji = data.get('emoji','🔥')
    if emoji not in ['🔥','😱','💰','👏','😂','🏏','⚡','💎']: return
    name = room['teams'].get(sid,{}).get('name') or room['spectators'].get(sid,{}).get('name','?')
    reaction = {'emoji': emoji, 'name': name, 'ts': time.time()}
    room['reactions'].append(reaction)
    socketio.emit('reaction', reaction, to=room_id)

@socketio.on('propose_set_jump')
def on_propose_set_jump(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['status'] not in ('bidding','sold','unsold'): return
    if sid_role.get(sid) == 'spectator': return
    set_id = data.get('set_id','')
    if set_id not in ALL_SETS: return
    proposer = room['teams'].get(sid,{}).get('name','?')
    vote = {'set_id': set_id, 'label': ALL_SETS[set_id], 'proposer': proposer, 'sid': sid}
    room['set_vote'] = vote
    socketio.emit('set_jump_proposed', {'vote': vote, 'room': pub(room)}, to=room_id)

@socketio.on('confirm_set_jump')
def on_confirm_set_jump(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    vote = room.get('set_vote')
    if not vote: return
    set_id = vote['set_id']
    auctioned = {p['name'] for p in room['sold_players']+room['unsold_players']}
    new_players = [
        dict(p, _set_id=set_id, _set_label=ALL_SETS[set_id], _set_start=False)
        for p in room['raw_players']
        if classify_player(p)==set_id and p['name'] not in auctioned
    ]
    if not new_players:
        emit('error', {'msg': 'No players left in that set!'}); return
    random.shuffle(new_players); new_players[0]['_set_start'] = True
    idx = room['player_index']
    room['players'] = room['players'][:idx+1] + new_players + room['players'][idx+1:]
    room['set_vote'] = None
    socketio.emit('set_jump_confirmed', {
        'set_label': ALL_SETS[set_id], 'count': len(new_players), 'room': pub(room)
    }, to=room_id)

@socketio.on('reject_set_jump')
def on_reject_set_jump(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    room['set_vote'] = None
    socketio.emit('set_jump_rejected', {'room': pub(room)}, to=room_id)

@socketio.on('propose_end_auction')
def on_propose_end(data):
    """Any bidder can propose ending the auction. Host sees a confirm dialog."""
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['status'] not in ('bidding','sold','unsold'): return
    if sid_role.get(sid) == 'spectator': return
    proposer = room['teams'].get(sid, {}).get('name', '?')
    # If host proposes, just end directly
    if sid == room['host_sid']:
        room['player_version'] += 1
        room['bid_version']    += 1
        room['reauction_pool'] = []
        _finish_auction_final(room_id)
        return
    socketio.emit('end_auction_proposed', {'proposer': proposer}, to=room_id)

@socketio.on('confirm_end_auction')
def on_confirm_end(data):
    """Host confirms the end auction proposal."""
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    room['player_version'] += 1
    room['bid_version']    += 1
    room['reauction_pool'] = []
    _finish_auction_final(room_id)

@socketio.on('reject_end_auction')
def on_reject_end(data):
    """Host rejects the end auction proposal."""
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if not room or room['host_sid'] != sid: return
    socketio.emit('end_auction_rejected', {}, to=room_id)

@socketio.on('get_state')
def on_get_state(data):
    sid = request.sid; room_id = sid_to_room.get(sid); room = rooms.get(room_id)
    if room: emit('full_state', pub(room))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
