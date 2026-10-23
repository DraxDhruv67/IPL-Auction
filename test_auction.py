import unittest
import json
import os
import sys

# Import app modules
import app as ipl_app
from app import (
    app, socketio, rooms, sid_to_room, sid_role,
    load_players, classify_player, arrange_in_sets,
    _bot_value_player, new_room, new_team, pub,
    INITIAL_BUDGET, TIMER_SECONDS, MIN_TIMER_AFTER_BID,
    _close_bid, _next_player, hash_pw
)

class TestIPLAuctionSuite(unittest.TestCase):
    def setUp(self):
        self.flask_client = app.test_client()
        # Reset server state between test runs
        rooms.clear()
        sid_to_room.clear()
        sid_role.clear()

    # ── 1. Dataset & Schema Tests ──────────────────────────────────────────────
    def test_01_players_load_successfully(self):
        players = load_players()
        self.assertIsInstance(players, list)
        self.assertGreater(len(players), 0)

    def test_02_player_schema_integrity(self):
        players = load_players()
        for p in players[:10]:
            self.assertIn('name', p)
            self.assertIn('role', p)
            self.assertIn('base_price', p)
            self.assertIn('nationality', p)
            self.assertIsInstance(p['base_price'], int)
            self.assertGreater(p['base_price'], 0)

    def test_03_player_classification_sets(self):
        p1 = {'role': 'Batsman', 'nationality': 'India', 'capped': True}
        p2 = {'role': 'Bowler', 'nationality': 'Australia', 'capped': True}
        p3 = {'role': 'Wicket-Keeper', 'nationality': 'India', 'capped': False}
        self.assertEqual(classify_player(p1), 'bat_ind_cap')
        self.assertEqual(classify_player(p2), 'bowl_foreign')
        self.assertEqual(classify_player(p3), 'wk_ind_uncap')

    def test_04_arrange_in_sets_ordering(self):
        raw = load_players()
        ordered = arrange_in_sets(raw)
        self.assertEqual(len(raw), len(ordered))
        self.assertTrue(ordered[0]['_set_start'])

    # ── 2. Auth & User Profile Tests ───────────────────────────────────────────
    def test_05_auth_register_validation(self):
        res = self.flask_client.post('/api/auth/register', json={'username': 'ab', 'password': '123'})
        self.assertEqual(res.status_code, 400)

    def test_06_auth_register_success(self):
        uname = f'testuser_{os.urandom(3).hex()}'
        res = self.flask_client.post('/api/auth/register', json={'username': uname, 'password': 'password123'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['user']['username'], uname)

    def test_07_auth_login_invalid(self):
        res = self.flask_client.post('/api/auth/login', json={'username': 'nonexistent', 'password': 'bad'})
        self.assertEqual(res.status_code, 401)

    def test_08_password_hash_deterministic(self):
        h1 = hash_pw('securepass')
        h2 = hash_pw('securepass')
        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, 'securepass')

    # ── 3. Room Lifecycle & Spectators ────────────────────────────────────────
    def test_09_room_creation(self):
        c1 = socketio.test_client(app)
        c1.emit('create_room', {'name': 'CSK Super Kings', 'bots': 0})
        received = c1.get_received()
        join_event = [e for e in received if e['name'] == 'room_joined']
        self.assertTrue(len(join_event) > 0)
        room_id = join_event[0]['args'][0]['room_id']
        self.assertIn(room_id, rooms)
        self.assertEqual(rooms[room_id]['status'], 'waiting')

    def test_10_join_nonexistent_room(self):
        c = socketio.test_client(app)
        c.emit('join_room_req', {'room_id': 'FAKE99', 'name': 'Player'})
        events = c.get_received()
        err = [e for e in events if e['name'] == 'error']
        self.assertTrue(len(err) > 0)

    def test_11_spectator_join_and_bid_block(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'HostTeam', 'bots': 0})
        room_id = host.get_received()[1]['args'][0]['room_id']

        spec = socketio.test_client(app)
        spec.emit('join_room_req', {'room_id': room_id, 'name': 'Watcher', 'spectator': True})
        
        # Start auction
        host.emit('start_auction', {})
        
        # Spectator attempts to place bid
        spec.emit('place_bid', {'amount': 10})
        err = [e for e in spec.get_received() if e['name'] == 'error']
        self.assertTrue(any("Spectators can't bid" in e['args'][0]['msg'] for e in err))

    # ── 4. Static Bidding Engine & Accuracy ───────────────────────────────────
    def test_12_static_bid_increment_10L(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'TeamA', 'bots': 0})
        r_id = host.get_received()[1]['args'][0]['room_id']

        user2 = socketio.test_client(app)
        user2.emit('join_room_req', {'room_id': r_id, 'name': 'TeamB'})

        host.emit('start_auction', {})
        initial_bid = rooms[r_id]['current_bid']

        # TeamB bids +10L
        user2.emit('place_bid', {'amount': 10})
        self.assertEqual(rooms[r_id]['current_bid'], initial_bid + 10)

    def test_13_static_bid_increment_50L(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'TeamA', 'bots': 0})
        r_id = host.get_received()[1]['args'][0]['room_id']
        host.emit('start_auction', {})
        initial_bid = rooms[r_id]['current_bid']

        host.emit('place_bid', {'amount': 50})
        self.assertEqual(rooms[r_id]['current_bid'], initial_bid + 50)

    def test_14_static_bid_increment_100L(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'TeamA', 'bots': 0})
        r_id = host.get_received()[1]['args'][0]['room_id']
        host.emit('start_auction', {})
        initial_bid = rooms[r_id]['current_bid']

        host.emit('place_bid', {'amount': 100})
        self.assertEqual(rooms[r_id]['current_bid'], initial_bid + 100)

    def test_15_static_bid_increment_200L(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'TeamA', 'bots': 0})
        r_id = host.get_received()[1]['args'][0]['room_id']
        host.emit('start_auction', {})
        initial_bid = rooms[r_id]['current_bid']

        host.emit('place_bid', {'amount': 200})
        self.assertEqual(rooms[r_id]['current_bid'], initial_bid + 200)

    def test_16_prevent_self_outbidding(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'TeamA', 'bots': 0})
        r_id = host.get_received()[1]['args'][0]['room_id']
        host.emit('start_auction', {})

        host.emit('place_bid', {'amount': 10})
        host.get_received() # Clear events
        host.emit('place_bid', {'amount': 10}) # Same bidder again
        err = [e for e in host.get_received() if e['name'] == 'error']
        self.assertTrue(any("already highest bidder" in e['args'][0]['msg'] for e in err))

    def test_17_budget_deduction_on_player_won(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'TeamA', 'bots': 0})
        r_id = host.get_received()[1]['args'][0]['room_id']
        host.emit('start_auction', {})

        base_p = rooms[r_id]['current_bid']
        host.emit('place_bid', {'amount': 50})
        winning_price = base_p + 50

        # Close bid
        _close_bid(r_id, rooms[r_id]['bid_version'])
        self.assertEqual(rooms[r_id]['status'], 'sold')
        team = list(rooms[r_id]['teams'].values())[0]
        self.assertEqual(team['budget'], INITIAL_BUDGET - winning_price)
        self.assertEqual(len(team['players']), 1)

    def test_18_reject_bid_exceeding_budget(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'TeamA', 'bots': 0})
        r_id = host.get_received()[1]['args'][0]['room_id']
        host_sid = rooms[r_id]['host_sid']
        rooms[r_id]['teams'][host_sid]['budget'] = 50

        host.emit('start_auction', {})
        host.emit('place_bid', {'amount': 100})
        err = [e for e in host.get_received() if e['name'] == 'error']
        self.assertTrue(any("Not enough budget" in e['args'][0]['msg'] for e in err))

    # ── 5. Bot AI Multi-Factor Valuation Tests ─────────────────────────────────
    def test_19_bot_initialization(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'Host', 'bots': 3})
        r_id = host.get_received()[1]['args'][0]['room_id']
        self.assertEqual(len(rooms[r_id]['bots']), 3)

    def test_20_bot_need_factor_scaling(self):
        r = new_room('TEST_R', 'host_sid', 'Host')
        bot_sid = 'bot_test_1'
        r['teams'][bot_sid] = new_team(bot_sid, 'RCB Bot', 1, is_bot=True)
        r['bots'][bot_sid] = {'style': 'smart', 'seed': 0.5}
        r['current_player'] = {'base_price': 100, 'rating': 85, 'role': 'Bowler'}

        # Case A: 0 bowlers in squad -> desperate need (1.4x factor)
        val_desperate = _bot_value_player(bot_sid, r)

        # Case B: Already has 4 bowlers in squad -> overstocked (0.65x factor)
        r['teams'][bot_sid]['players'] = [{'role': 'Bowler'} for _ in range(4)]
        val_stocked = _bot_value_player(bot_sid, r)

        self.assertGreater(val_desperate, val_stocked)

    def test_21_bot_personality_aggressive_vs_conservative(self):
        r = new_room('TEST_R2', 'host_sid', 'Host')
        r['current_player'] = {'base_price': 200, 'rating': 80, 'role': 'Batsman'}
        
        # Aggressive bot
        b_agg = 'bot_agg'
        r['teams'][b_agg] = new_team(b_agg, 'AggroBot', 1, is_bot=True)
        r['bots'][b_agg] = {'style': 'aggressive', 'seed': 0.5}
        val_agg = _bot_value_player(b_agg, r)

        # Conservative bot
        b_con = 'bot_con'
        r['teams'][b_con] = new_team(b_con, 'ConBot', 2, is_bot=True)
        r['bots'][b_con] = {'style': 'conservative', 'seed': 0.5}
        val_con = _bot_value_player(b_con, r)

        self.assertGreater(val_agg, val_con)

    # ── 6. Timer, Versioning & Race Conditions ─────────────────────────────────
    def test_22_timer_buffer_on_bid(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'Host', 'bots': 0})
        r_id = host.get_received()[1]['args'][0]['room_id']
        host.emit('start_auction', {})

        # Lower timer to 3 seconds
        rooms[r_id]['timer'] = 3
        host.emit('place_bid', {'amount': 10})
        # Should be buffered to MIN_TIMER_AFTER_BID (10s)
        self.assertEqual(rooms[r_id]['timer'], MIN_TIMER_AFTER_BID)

    def test_23_stale_bid_version_double_close_guard(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'Host', 'bots': 0})
        r_id = host.get_received()[1]['args'][0]['room_id']
        host.emit('start_auction', {})

        old_ver = rooms[r_id]['bid_version']
        # Another bid lands
        host.emit('place_bid', {'amount': 10})
        # Stale close call with old version should be cleanly ignored
        _close_bid(r_id, expected_bid_version=old_ver)
        self.assertEqual(rooms[r_id]['status'], 'bidding')

    # ── 7. Sets, Skip & Re-Auction Transitions ─────────────────────────────────
    def test_24_unsold_player_enters_reauction_pool(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'Host', 'bots': 0})
        r_id = host.get_received()[1]['args'][0]['room_id']
        host.emit('start_auction', {})

        # No bids placed -> player unsold
        _close_bid(r_id, rooms[r_id]['bid_version'])
        self.assertEqual(rooms[r_id]['status'], 'unsold')
        self.assertEqual(len(rooms[r_id]['unsold_players']), 1)
        self.assertEqual(len(rooms[r_id]['reauction_pool']), 1)
        self.assertEqual(rooms[r_id]['reauction_pool'][0]['_set_id'], 'unsold')

    def test_25_host_force_skip_player(self):
        host = socketio.test_client(app)
        host.emit('create_room', {'name': 'Host', 'bots': 0})
        r_id = host.get_received()[1]['args'][0]['room_id']
        host.emit('start_auction', {})

        host.emit('vote_skip', {})
        self.assertEqual(rooms[r_id]['status'], 'unsold')
        self.assertEqual(len(rooms[r_id]['reauction_pool']), 1)

    # ── 8. Production WSGI & Configuration ─────────────────────────────────────
    def test_26_procfile_references_existing_app(self):
        with open('Procfile', 'r') as f:
            proc = f.read().strip()
        self.assertIn('app:app', proc)
        self.assertNotIn('server:app', proc)

    def test_27_gitignore_exists(self):
        self.assertTrue(os.path.exists('.gitignore'))

if __name__ == '__main__':
    unittest.main(verbosity=2)
