/* IPL MEGA AUCTION 2025 */
const socket = io();

let mySid='', myName='', myRoomId='', isHost=false, roomState=null;
let currentUser = JSON.parse(localStorage.getItem('ipl_user') || 'null');
const TIMER_MAX = 20;

/* ── Audio ── */
let actx;
function _audio(){if(!actx)actx=new(window.AudioContext||window.webkitAudioContext)();}
function beep(f,d,t='sine',v=.22){try{_audio();const o=actx.createOscillator(),g=actx.createGain();o.connect(g);g.connect(actx.destination);o.type=t;o.frequency.value=f;g.gain.setValueAtTime(v,actx.currentTime);g.gain.exponentialRampToValueAtTime(.001,actx.currentTime+d);o.start();o.stop(actx.currentTime+d);}catch(e){}}
const sndBid=()=>beep(660,.08,'square',.18);
const sndNew=()=>[400,530,720].forEach((f,i)=>setTimeout(()=>beep(f,.12,'sine',.22),i*80));
const sndSold=()=>[500,700,900,700].forEach((f,i)=>setTimeout(()=>beep(f,.15,'triangle',.28),i*90));
const sndUnsold=()=>[400,300,200].forEach((f,i)=>setTimeout(()=>beep(f,.12,'sawtooth',.18),i*90));
const sndUrgent=()=>beep(900,.04,'square',.12);

/* ── Utils ── */
function fmt(l){if(l==null)return'—';if(l>=100)return`₹${(l/100).toFixed(l%100===0?0:1)} Cr`;return`₹${l} L`;}
const ROLE_CSS={Batsman:'role-bat',Bowler:'role-bowl','All-Rounder':'role-ar','Wicket-Keeper':'role-wk'};
const ROLE_EMOJI={Batsman:'🏏',Bowler:'🎯','All-Rounder':'⚡','Wicket-Keeper':'🧤'};
const ROLE_ORDER=['Batsman','Wicket-Keeper','All-Rounder','Bowler'];
const ROLE_COL={Batsman:'bat','Wicket-Keeper':'wk','All-Rounder':'ar',Bowler:'bowl'};
function $id(id){return document.getElementById(id);}
function showScreen(id){document.querySelectorAll('.screen').forEach(s=>s.classList.remove('active'));$id(id).classList.add('active');}
function toast(msg,type='info'){const c=$id('toast-container'),d=document.createElement('div');d.className=`toast ${type}`;d.textContent=msg;c.appendChild(d);setTimeout(()=>{d.style.animation='toastOut .3s ease forwards';setTimeout(()=>d.remove(),300);},3000);}
function feed(msg,type='info'){const f=$id('live-feed');if(!f)return;const el=document.createElement('div');el.className=`feed-item ${type}`;el.textContent=msg;f.insertBefore(el,f.firstChild);while(f.children.length>60)f.removeChild(f.lastChild);
  // mirror to mobile feed
  const mf=$id('m-feed-list');if(mf){const mel=document.createElement('div');mel.className=`feed-item ${type}`;mel.textContent=msg;mf.insertBefore(mel,mf.firstChild);while(mf.children.length>30)mf.removeChild(mf.lastChild);}
}

/* ══════════════════════════════════════
   AUTH
   ══════════════════════════════════════ */
function authTab(tab){
  document.querySelectorAll('.auth-tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.auth-panel').forEach(p=>p.classList.add('hidden'));
  event.target.classList.add('active');
  $id(`auth-${tab}`).classList.remove('hidden');
}
function skipAuth(){showScreen('screen-lobby');updateUserBadge();}
async function doLogin(){
  const user=($id('login-user').value||'').trim();
  const pass=($id('login-pass').value||'').trim();
  if(!user||!pass){showAuthErr('login','Fill in all fields');return;}
  const res=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:user,password:pass})});
  const data=await res.json();
  if(!data.ok){showAuthErr('login',data.msg);return;}
  currentUser=data.user;
  localStorage.setItem('ipl_user',JSON.stringify(currentUser));
  showScreen('screen-lobby');updateUserBadge();
  toast(`Welcome back, ${currentUser.display}! 🏏`,'success');
}
async function doRegister(){
  const user=($id('reg-user').value||'').trim();
  const disp=($id('reg-display').value||'').trim()||user;
  const pass=($id('reg-pass').value||'').trim();
  if(!user||!pass){showAuthErr('register','Fill in all fields');return;}
  const res=await fetch('/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:user,password:pass,display:disp})});
  const data=await res.json();
  if(!data.ok){showAuthErr('register',data.msg);return;}
  currentUser=data.user;
  localStorage.setItem('ipl_user',JSON.stringify(currentUser));
  showScreen('screen-lobby');updateUserBadge();
  toast(`Account created! Welcome, ${currentUser.display} 🎉`,'success');
}
function showAuthErr(panel,msg){const el=$id(`${panel}-err`);el.textContent=msg;el.classList.remove('hidden');setTimeout(()=>el.classList.add('hidden'),4000);}
function logout(){currentUser=null;localStorage.removeItem('ipl_user');showScreen('screen-auth');updateUserBadge();}
function updateUserBadge(){
  const badge=$id('user-badge'),name=$id('user-badge-name');
  if(currentUser&&badge){badge.classList.remove('hidden');if(name)name.textContent=currentUser.display||currentUser.username;}
  else if(badge) badge.classList.add('hidden');
  // pre-fill team name from display name
  if(currentUser){const inp=$id('inp-name');if(inp&&!inp.value)inp.value=currentUser.display||'';}
}
async function showProfile(){
  if(!currentUser)return;
  showScreen('screen-profile');
  const res=await fetch(`/api/profile/${currentUser.username}`);
  const data=await res.json();
  if(!data.ok){$id('profile-body').innerHTML='<p style="color:var(--dim);padding:20px">Failed to load profile</p>';return;}
  const recs=data.records||[];
  const totalSpend=recs.reduce((s,r)=>s+(r.total_spend||0),0);
  const totalPlayers=recs.reduce((s,r)=>s+(r.players_won||0),0);
  $id('profile-body').innerHTML=`
    <div class="profile-stat-row">
      <div class="pstat"><div class="pstat-val">${recs.length}</div><div class="pstat-label">AUCTIONS</div></div>
      <div class="pstat"><div class="pstat-val">${totalPlayers}</div><div class="pstat-label">PLAYERS WON</div></div>
      <div class="pstat"><div class="pstat-val">${fmt(totalSpend)}</div><div class="pstat-label">TOTAL SPENT</div></div>
    </div>
    <h3 style="font-family:var(--fd);font-size:20px;letter-spacing:2px;color:var(--gold);margin:4px 0">RECENT AUCTIONS</h3>
    ${recs.length?recs.map(r=>`
      <div class="record-card">
        <div class="record-date">${r.date} · Room ${r.room_id}</div>
        <div class="record-team">${r.team_name}</div>
        <div class="record-stats">
          <div class="rstat">Players won: <span>${r.players_won}</span></div>
          <div class="rstat">Spent: <span>${fmt(r.total_spend)}</span></div>
          <div class="rstat">Left: <span>${fmt(r.budget_left)}</span></div>
        </div>
        ${r.squad&&r.squad.length?`<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px">
          ${r.squad.slice(0,6).map(p=>`<span style="background:var(--bg3);border:1px solid var(--bord);border-radius:5px;padding:2px 8px;font-size:11px">${p.name}</span>`).join('')}
          ${r.squad.length>6?`<span style="color:var(--dim);font-size:11px;align-self:center">+${r.squad.length-6} more</span>`:''}
        </div>`:''}
      </div>`).join(''):'<p style="color:var(--dim);font-size:13px">No auctions yet. Play and your records will appear here!</p>'}`;
}

/* ══════════════════════════════════════
   LOBBY
   ══════════════════════════════════════ */
function createRoom(){
  myName=($id('inp-name').value||'').trim();
  if(!myName){toast('Enter a team name!','error');return;}
  _audio();
  const checkboxes=document.querySelectorAll('.set-checks input[type=checkbox]');
  const all=Array.from(checkboxes), selected=all.filter(c=>c.checked).map(c=>c.value);
  const sets=selected.length===all.length?null:selected; // null = all sets
  socket.emit('create_room',{name:myName,username:currentUser?.username||'',selected_sets:sets});
}
function toggleSetPicker(){
  const p=$id('set-picker'),a=$id('set-picker-arrow');
  p.classList.toggle('hidden');a.textContent=p.classList.contains('hidden')?'▼':'▲';
}
function joinRoom(code, asSpectator=false){
  myName=($id('inp-name').value||'').trim();
  code=(code||$id('inp-room').value||'').trim().toUpperCase();
  if(!myName){toast('Enter a team name!','error');return;}
  if(!code){toast('Enter a room code!','error');return;}
  _audio();
  socket.emit('join_room_req',{name:myName,room_id:code,username:currentUser?.username||'',spectator:asSpectator});
}
function startAuction(){socket.emit('start_auction',{});}
function nextPlayer(){socket.emit('next_player',{});}
function placeBid(amt){socket.emit('place_bid',{amount:amt});}
function stopAuction(){if(!confirm('End the auction now and go to results?'))return;socket.emit('stop_auction',{});}
function skipPlayer(){if(!isHost)return;socket.emit('skip_player',{});}
/* ── SET JUMP ── */
let _setJumpSets=[];
function openSetJumpPanel(){
  if(!roomState) return;
  const opts=$id('set-jump-options'); if(!opts) return;
  const sets=(roomState.remaining_sets||[]);
  if(!sets.length){toast('No other sets available!','error');return;}
  _setJumpSets=sets;
  opts.innerHTML=sets.map(s=>`
    <button class="set-jump-opt" onclick="proposeSetJump('${s.id}','${s.label.replace(/'/g,'&#39;')}')">
      ${s.label}
    </button>`).join('');
  $id('set-jump-panel').classList.remove('hidden');
}
function closeSetJumpPanel(){ $id('set-jump-panel').classList.add('hidden'); }
function proposeSetJump(setId, label){
  socket.emit('propose_set_jump',{set_id:setId});
  closeSetJumpPanel();
  toast(`📋 Proposed: ${label}`,'info');
}
function confirmSetJump(){ socket.emit('confirm_set_jump',{}); $id('set-jump-host-modal').classList.add('hidden'); }
function rejectSetJump()  { socket.emit('reject_set_jump',{});  $id('set-jump-host-modal').classList.add('hidden'); }

function sendReaction(emoji){socket.emit('send_reaction',{emoji});}
function startReauction(){$id('reauction-modal').classList.add('hidden');socket.emit('start_reauction',{});}
function skipReauction(){$id('reauction-modal').classList.add('hidden');socket.emit('skip_reauction',{});}

/* ══════════════════════════════════════
   RENDER
   ══════════════════════════════════════ */
function renderWaitTeams(teams){
  const el=$id('teams-waiting');if(!el)return;
  el.innerHTML=teams.map(t=>{const ini=t.name.split(' ').map(w=>w[0]).join('').toUpperCase().slice(0,2);return`<div class="team-card-wait"><div class="team-avatar" style="background:${t.color}">${ini}</div><div class="name">${t.name}</div></div>`;}).join('');
  const cnt=$id('team-count');if(cnt)cnt.textContent=teams.length;
}
function renderTeamsPanel(teams){
  // Update spectator count
  if(roomState){
    const sc=$id('spectator-count');
    if(sc){
      const n=roomState.spectator_count||0;
      sc.classList.toggle('hidden',n===0);
      sc.textContent=`👁 ${n} watching`;
    }
  }
  const html=teams.map(t=>{const bidding=roomState&&roomState.current_bidder_sid===t.sid,me=t.sid===mySid;return`<div class="team-row${bidding?' bidding':''}${me?' my-team':''}${t.is_bot?' bot-team':''}"><div class="t-name">${me?'★ ':''}${t.is_bot?'🤖 ':''}${t.name}</div><div class="t-budget">${fmt(t.budget)}</div><div class="t-count">🏏 ${t.players.length}</div></div>`;}).join('');
  [$id('teams-list'),$id('m-teams-list')].forEach(el=>{if(el)el.innerHTML=html;});
}
function renderPlayerCard(player){
  const cls=ROLE_CSS[player.role]||'role-bat',emoji=ROLE_EMOJI[player.role]||'🏏';
  const setHdr=player._set_start?`<div class="set-header-banner">${player._set_label||''}</div>`:'';
  $id('player-stage').innerHTML=`${setHdr}
    <div class="player-card">
      <div class="player-number">${player.id||''}</div>
      <div class="player-role-badge ${cls}">${emoji} ${player.role}</div>
      <div class="player-name">${player.name}</div>
      <div class="player-meta">
        <span class="meta-item">🌍 ${player.nationality||'India'}</span>
        ${player.team?`<span class="meta-item">🏟️ ${player.team}</span>`:''}
        ${player.rating?`<span class="meta-item">⭐ ${player.rating}</span>`:''}
      </div>
      <div class="player-base-price"><div class="base-price-label">BASE PRICE</div><div class="base-price-val">${fmt(player.base_price)}</div></div>
    </div>
    <div id="result-banner" class="result-banner hidden"></div>`;
}
function updateBid(bid,bidderName,bidderColor,bidderSid){
  const amt=$id('bid-amount'),ldr=$id('bid-leader');if(!amt)return;
  amt.textContent=fmt(bid);
  if(bidderName){ldr.textContent=`🏅 ${bidderName}`;ldr.className='bid-leader active';ldr.style.color=bidderSid===mySid?'var(--green)':(bidderColor||'');}
  else{ldr.textContent='No bids yet';ldr.className='bid-leader';ldr.style.color='';}
  const w=amt.closest('.current-bid-display');if(w){w.classList.remove('bid-flash');void w.offsetWidth;w.classList.add('bid-flash');}
}
function updateTimer(t){
  const ring=$id('timer-ring'),txt=$id('timer-text');if(!ring||!txt)return;
  ring.style.strokeDashoffset=2*Math.PI*42*(1-Math.max(0,t)/TIMER_MAX);
  txt.textContent=t>0?t:'0';
  ring.classList.toggle('urgent',t>0&&t<=5);txt.classList.toggle('urgent',t>0&&t<=5);
  if(t>0&&t<=5)sndUrgent();
}
function updateProgress(sold,total){
  const bar=$id('progress-bar'),txt=$id('progress-text');if(!bar)return;
  bar.style.width=total>0?(sold/total*100)+'%':'0%';if(txt)txt.textContent=`${sold} / ${total}`;
}
function updateMyBudget(){if(!roomState)return;const me=roomState.teams.find(t=>t.sid===mySid);if(me)$id('your-budget').textContent=fmt(me.budget);}
function showBanner(html,cls){
  const el=$id('result-banner');if(!el)return;
  el.innerHTML=html;el.className=`result-banner ${cls}`;el.classList.remove('hidden');
  const stage=$id('player-stage');if(stage)setTimeout(()=>stage.scrollTo({top:stage.scrollHeight,behavior:'smooth'}),60);
}

/* ══════════════════════════════════════
   SOCKET EVENTS
   ══════════════════════════════════════ */
socket.on('connected',d=>{mySid=d.sid;});
let isSpectator=false;
socket.on('room_joined',d=>{
  roomState=d.room;myRoomId=d.room_id;mySid=d.your_sid;
  isHost=d.room.host_sid===mySid;
  isSpectator=(d.role==='spectator');
  $id('disp-room-id').textContent=myRoomId;$id('top-room-id').textContent=myRoomId;
  renderWaitTeams(d.room.teams);
  $id('host-controls').classList.toggle('hidden',!isHost);
  $id('guest-wait').classList.toggle('hidden',isHost);
  const sb=$id('spectator-badge'); if(sb) sb.classList.toggle('hidden',!isSpectator);
  showScreen('screen-waiting');
});
socket.on('room_update',d=>{
  roomState=d;if(d.host_sid)isHost=d.host_sid===mySid;
  if($id('screen-waiting').classList.contains('active'))renderWaitTeams(d.teams);
  renderTeamsPanel(d.teams);updateMyBudget();
  if(['sold','unsold'].includes(d.status)&&isHost)$id('host-next').classList.remove('hidden');
});
socket.on('notification',d=>{toast(d.msg,'info');feed(d.msg,'info');});
socket.on('new_player',d=>{
  roomState=d.room;showScreen('screen-auction');
  $id('host-next').classList.add('hidden');
  renderTeamsPanel(d.room.teams);renderPlayerCard(d.player);
  updateBid(d.player.base_price,null,null,null);
  updateProgress(d.room.sold_count,d.room.total_players);updateMyBudget();updateTimer(TIMER_MAX);
  $id('bid-section').classList.toggle('hidden', isSpectator);
  // Show jump button: host sees it in host-next, guests get their own row
  const gjr=$id('guest-jump-row');
  if(gjr) gjr.classList.toggle('hidden', isHost||isSpectator);
  const stage=$id('player-stage');if(stage)stage.scrollTop=0;
  feed(`🆕 ${d.player.name} (${d.player.role})`,'new');sndNew();updateDrawer(d.room);
});
socket.on('bid_update',d=>{
  roomState=d.room;updateBid(d.bid,d.bidder,d.bidder_color,d.bidder_sid);
  updateTimer(d.timer);renderTeamsPanel(d.room.teams);
  feed(`💰 ${d.bidder}: ${fmt(d.bid)}`,'bid');sndBid();
});
socket.on('timer_tick',d=>{updateTimer(d.timer);});
socket.on('player_sold',d=>{
  roomState=d.room;renderTeamsPanel(d.room.teams);updateProgress(d.room.sold_count,d.room.total_players);updateMyBudget();
  $id('bid-section').classList.add('hidden');updateTimer(0);
  showBanner(`<div style="font-size:28px;margin-bottom:5px">🎉 SOLD!</div><div style="font-family:var(--fd);font-size:22px;color:#fff">${d.player.name}</div><div style="font-family:var(--fm);font-size:24px;color:var(--gold);margin:5px 0">${fmt(d.price)}</div><div style="font-size:13px;font-weight:700;color:${d.color||'var(--green)'}">▶ ${d.team}</div>`,'sold-banner');
  feed(`✅ ${d.player.name} → ${d.team} @ ${fmt(d.price)}`,'sold');sndSold();updateDrawer(d.room);
  if(isHost)$id('host-next').classList.remove('hidden');
});
socket.on('player_unsold',d=>{
  roomState=d.room;$id('bid-section').classList.add('hidden');updateTimer(0);
  showBanner(`<div style="font-size:28px;margin-bottom:5px">❌ UNSOLD</div><div style="font-family:var(--fd);font-size:22px;color:var(--dim)">${d.player.name}</div><div style="color:var(--red);font-size:12px;margin-top:5px">No bids placed</div>`,'unsold-banner');
  feed(`❌ ${d.player.name} — unsold`,'info');sndUnsold();updateDrawer(d.room);
  if(isHost)$id('host-next').classList.remove('hidden');
});
socket.on('set_jump_proposed',d=>{
  roomState=d.room;
  if(isHost){
    const vote=d.vote;
    $id('set-jump-host-msg').textContent=`${vote.proposer} wants to jump to: ${vote.label}. Approve?`;
    $id('set-jump-host-modal').classList.remove('hidden');
  } else {
    toast(`📋 ${d.vote.proposer} proposed: ${d.vote.label}`,'info');
  }
});
socket.on('set_jump_confirmed',d=>{
  roomState=d.room;
  toast(`📋 Jumping to ${d.set_label} (${d.count} players added)!`,'success');
  feed(`📋 Set changed → ${d.set_label}`,'new');
});
socket.on('set_jump_rejected',d=>{
  roomState=d.room;
  toast('Set jump rejected by host','error');
});

socket.on('reaction',d=>{
  const feed=$id('reaction-feed'); if(!feed) return;
  const el=document.createElement('div');
  el.className='reaction-item';
  el.innerHTML=`<span>${d.emoji}</span><span style="color:var(--dim);font-size:10px">${d.name}</span>`;
  feed.appendChild(el);
  setTimeout(()=>el.remove(),4000);
});

socket.on('reauction_available',d=>{
  roomState=d.room;
  const modal=$id('reauction-modal'); if(!modal) return;
  $id('reauction-msg').textContent=`${d.count} player(s) went unsold: ${d.players.slice(0,5).join(', ')}${d.count>5?'…':''}. Start a re-auction round?`;
  if(isHost) modal.classList.remove('hidden');
  else toast(`🔄 ${d.count} unsold players — host deciding on re-auction…`,'info');
});

socket.on('reauction_started',d=>{
  roomState=d.room;
  toast('🔄 RE-AUCTION ROUND STARTING!','success');
  const stage=$id('player-stage');
  if(stage) stage.innerHTML=`<div class="stage-idle"><div class="reauction-banner">🔄 RE-AUCTION ROUND</div><p style="color:var(--dim);margin-top:10px">Unsold players going under the hammer again…</p></div>`;
});

socket.on('auction_finished',d=>{
  showScreen('screen-finished');
  setTimeout(()=>{renderSquads(d.room.teams);renderFormation(d.room.teams);renderLeaderboard(d.room.teams);},120);
});
socket.on('error',d=>{toast('⚠️ '+d.msg,'error');});
socket.on('full_state',d=>{
  roomState=d;if(d.host_sid)isHost=d.host_sid===mySid;renderTeamsPanel(d.teams);updateMyBudget();
  if(d.status==='bidding'&&d.current_player){showScreen('screen-auction');renderPlayerCard(d.current_player);updateBid(d.current_bid,d.current_bidder_name,null,d.current_bidder_sid);updateTimer(d.timer);updateProgress(d.sold_count,d.total_players);$id('bid-section').classList.remove('hidden');$id('host-next').classList.add('hidden');updateDrawer(d);}
});

/* ── Active rooms ── */
function loadRooms(){fetch('/api/rooms').then(r=>r.json()).then(list=>{const el=$id('lobby-rooms');if(!el)return;if(!list.length){el.innerHTML='';return;}el.innerHTML=`<div style="font-size:10px;color:var(--dim);letter-spacing:3px;margin-bottom:6px;font-family:var(--fm)">ACTIVE ROOMS</div>`+list.map(r=>`<div class="room-item" onclick="joinRoom('${r.id}')"><span>🏟️ <b>${r.host}</b></span><span style="color:var(--dim);font-size:11px">${r.teams} teams · ${r.id}</span></div>`).join('');}).catch(()=>{});}
setInterval(()=>{if($id('screen-lobby')&&$id('screen-lobby').classList.contains('active'))loadRooms();},5000);
loadRooms();

/* ── Keyboard ── */
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT')return;
  if(!$id('screen-auction').classList.contains('active'))return;
  if(e.key==='1')placeBid(10);if(e.key==='2')placeBid(50);if(e.key==='3')placeBid(100);if(e.key==='4')placeBid(500);
  if((e.key==='n'||e.key==='N')&&isHost)nextPlayer();
});
$id('inp-name').addEventListener('keydown',e=>{if(e.key==='Enter')createRoom();});
$id('inp-room').addEventListener('keydown',e=>{if(e.key==='Enter')joinRoom();});

/* ══════════════════════════════════════
   MOBILE PANELS
   ══════════════════════════════════════ */
let activeMobilePanel=null;
function toggleMobilePanel(id){
  if(activeMobilePanel===id){closeMobilePanel(id);return;}
  if(activeMobilePanel)closeMobilePanel(activeMobilePanel);
  const el=$id(id);if(el){el.classList.remove('hidden');el.classList.add('visible');}
  activeMobilePanel=id;
}
function closeMobilePanel(id){const el=$id(id);if(el){el.classList.remove('visible');el.classList.add('hidden');}activeMobilePanel=null;}
// Close mobile panels when tapping outside
document.addEventListener('click',e=>{
  if(activeMobilePanel&&!e.target.closest('.mobile-panel')&&!e.target.closest('.mbar-btn')){closeMobilePanel(activeMobilePanel);}
});

/* ══════════════════════════════════════
   DRAWER
   ══════════════════════════════════════ */
let drawerOpen=false;
document.addEventListener('DOMContentLoaded',()=>{
  const d=$id('drawer');if(!d)return;
  let y0=0;
  d.addEventListener('touchstart',e=>{y0=e.touches[0].clientY;},{passive:true});
  d.addEventListener('touchend',e=>{const dy=y0-e.changedTouches[0].clientY;if(dy>40)openDrawer();if(dy<-40)closeDrawer();},{passive:true});
});
function openDrawer(){const d=$id('drawer');if(d){d.classList.add('open');drawerOpen=true;}}
function closeDrawer(){const d=$id('drawer');if(d){d.classList.remove('open');drawerOpen=false;}}
function toggleDrawer(){drawerOpen?closeDrawer():openDrawer();}
function switchTab(btn,panelId){
  document.querySelectorAll('.drawer-tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.drawer-panel').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');$id(panelId).classList.add('active');openDrawer();
}
function renderMySquad(room){
  const me=room.teams.find(t=>t.sid===mySid),el=$id('squad-list'),badge=$id('squad-count');if(!el)return;
  if(!me||!me.players.length){el.innerHTML='<div class="drawer-empty">No players won yet</div>';if(badge)badge.textContent='0';return;}
  if(badge)badge.textContent=me.players.length;
  const grouped={};ROLE_ORDER.forEach(r=>grouped[r]=[]);me.players.forEach(p=>{(grouped[p.role]=grouped[p.role]||[]).push(p);});
  let html='';ROLE_ORDER.forEach(role=>{const ps=grouped[role]||[];if(!ps.length)return;html+=`<div class="squad-role-sep">${ROLE_EMOJI[role]} ${role}</div>`;ps.forEach(p=>{html+=`<div class="squad-card"><div class="sc-name">${p.name}</div><div class="sc-price">${fmt(p.sold_price)}</div></div>`;});});
  el.innerHTML=html;
  const h=document.querySelector('.drawer-handle');if(h&&!drawerOpen){h.classList.remove('drawer-pulse');void h.offsetWidth;h.classList.add('drawer-pulse');setTimeout(()=>h.classList.remove('drawer-pulse'),1000);}
}
function renderUpcoming(room){
  const list=room.upcoming_players||[],el=$id('upcoming-list'),badge=$id('upcoming-count');if(!el)return;
  if(!list.length){el.innerHTML='<div class="drawer-empty">No more players</div>';if(badge)badge.textContent='0';return;}
  if(badge)badge.textContent=room.players_left>0?room.players_left:list.length;
  el.innerHTML=list.map((p,i)=>`<div class="upcoming-card${i===0?' next-up':''}">${i===0?'<div class="next-up-label">NEXT</div>':''}<div class="uc-name">${p.name}</div><div class="uc-role">${ROLE_EMOJI[p.role]||''} ${p.role}</div><div class="uc-price">${fmt(p.base_price)}</div>${p._set_start?`<div class="uc-set">${p._set_label||''}</div>`:''}</div>`).join('');
}
function updateDrawer(room){renderMySquad(room);renderUpcoming(room);}

/* ══════════════════════════════════════
   FINISHED SCREEN
   ══════════════════════════════════════ */
function finTab(btn,sid){document.querySelectorAll('.fin-tab').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.fin-section').forEach(s=>s.classList.remove('active'));btn.classList.add('active');$id(sid).classList.add('active');}
function groupByRole(players){const g={Batsman:[],'Wicket-Keeper':[],'All-Rounder':[],Bowler:[]};players.forEach(p=>{(g[p.role]=g[p.role]||[]).push(p);});return g;}
function renderSquads(teams){
  const el=$id('squads-grid');if(!el)return;
  el.innerHTML=teams.map(t=>{
    if(!t.players||!t.players.length)return`<div class="squad-full-card"><div class="squad-full-header" style="border-top:3px solid ${t.color}"><div class="squad-full-name" style="color:${t.color}">${t.name}</div><div class="squad-full-budget">${fmt(t.budget)} left</div></div><div style="padding:14px;color:var(--dim);font-size:13px">No players</div></div>`;
    const g=groupByRole(t.players);
    const blocks=ROLE_ORDER.map(role=>{const ps=g[role]||[];if(!ps.length)return'';return`<div class="squad-role-group"><div class="squad-role-label ${ROLE_COL[role]}">${ROLE_EMOJI[role]} ${{"Batsman":"Batsmen","Wicket-Keeper":"Wicket-Keepers","All-Rounder":"All-Rounders","Bowler":"Bowlers"}[role]||role} (${ps.length})</div>${ps.map(p=>`<div class="squad-player-row"><span>${p.name}</span><span class="sp-price">${fmt(p.sold_price)}</span></div>`).join('')}</div>`;}).join('');
    return`<div class="squad-full-card"><div class="squad-full-header" style="border-top:3px solid ${t.color}"><div class="squad-full-name" style="color:${t.color}">${t.name}</div><div class="squad-full-budget">💰 ${fmt(t.budget)} · 🏏 ${t.players.length}</div></div>${blocks}</div>`;
  }).join('');
}
const KR={'Virat Kohli':90,'Rohit Sharma':86,'Jasprit Bumrah':90,'Rashid Khan':88,'MS Dhoni':85,'Hardik Pandya':82,'Ravindra Jadeja':84,'Rishabh Pant':84,'Jos Buttler':83,'Pat Cummins':83,'Travis Head':82,'Andre Russell':82,'Mitchell Starc':83,'Yashasvi Jaiswal':82,'Shubman Gill':83,'Heinrich Klaasen':82,'Suryakumar Yadav':84,'KL Rahul':81,'Axar Patel':78,'Kuldeep Yadav':79,'Mohammed Shami':81,'Kagiso Rabada':82,'Trent Boult':79,'Yuzvendra Chahal':77,'Sam Curran':77,'Glenn Maxwell':79,'Sunil Narine':80,'Ben Stokes':81};
function pRating(p){if(p.rating&&p.rating>60)return p.rating;if(KR[p.name])return KR[p.name];const b={Batsman:65,'Wicket-Keeper':65,'All-Rounder':67,Bowler:65}[p.role]||65;return Math.min(88,b+Math.min(15,Math.floor((p.sold_price||0)/100)));}
function analyseTeam(team){
  if(!team.players||!team.players.length)return null;
  const g=groupByRole(team.players);
  const bats=g.Batsman||[],wks=g['Wicket-Keeper']||[],ars=g['All-Rounder']||[],bowls=g.Bowler||[];
  const ranked=r=>[...r].sort((a,b)=>pRating(b)-pRating(a));
  const wkP=ranked(wks).slice(0,1),batP=ranked(bats).slice(0,4),arP=ranked(ars).slice(0,2),bowlP=ranked(bowls).slice(0,4);
  let xi=[...wkP,...batP,...arP,...bowlP];const used=new Set(xi.map(p=>p.name));
  xi.push(...ranked(team.players.filter(p=>!used.has(p.name))).slice(0,11-xi.length));xi=xi.slice(0,11);
  const avg=xi.length?Math.round(xi.reduce((s,p)=>s+pRating(p),0)/xi.length):0;
  const overall=Math.min(99,(bats.length>=4?25:Math.round(bats.length/4*25))+(bowls.length>=4?25:Math.round(bowls.length/4*25))+(ars.length>=2?20:Math.round(ars.length/2*20))+(wks.length>=1?15:0)+Math.round(Math.max(0,avg-65)/25*15));
  return{xi,wkP,batP,arP,bowlP,avg,overall,counts:{bat:bats.length,wk:wks.length,ar:ars.length,bowl:bowls.length}};
}
function rColor(r){return r>=80?'#06D6A0':r>=70?'#FFD700':'#f4a261';}
function pRow(pl,cls,lbl){if(!pl.length)return'';return`<div class="pitch-row">${pl.map(p=>`<div class="pitch-player ${cls}"><div>${p.name.split(' ').slice(-1)[0]}</div><div class="pitch-label">${lbl}</div></div>`).join('')}</div>`;}
function renderFormation(teams){
  const el=$id('formation-grid');if(!el)return;
  el.innerHTML=teams.map(t=>{
    const a=analyseTeam(t);if(!a)return`<div class="formation-card"><div class="formation-card-header" style="border-top:3px solid ${t.color}"><div class="formation-card-name" style="color:${t.color}">${t.name}</div></div><div style="padding:14px;color:var(--dim);font-size:13px">No players</div></div>`;
    const bar=Math.round(a.overall/99*100);
    return`<div class="formation-card"><div class="formation-card-header" style="border-top:3px solid ${t.color}"><div class="formation-card-name" style="color:${t.color}">${t.name}</div><div class="formation-xi-badge">BEST XI · ${a.xi.length}</div></div><div class="pitch-wrap"><div class="pitch-lines"></div><div class="pitch-center"></div>${pRow(a.bowlP,'bowl','BOWL')}${pRow(a.arP,'ar','AR')}${pRow(a.batP,'bat','BAT')}${pRow(a.wkP,'wk','WK')}</div><div class="formation-stats"><div class="fstat"><div class="fstat-val">${a.counts.bat}</div><div class="fstat-label">BAT</div></div><div class="fstat"><div class="fstat-val">${a.counts.wk}</div><div class="fstat-label">WK</div></div><div class="fstat"><div class="fstat-val">${a.counts.ar}</div><div class="fstat-label">AR</div></div><div class="fstat"><div class="fstat-val">${a.counts.bowl}</div><div class="fstat-label">BOWL</div></div></div><div class="overall-rating"><div class="or-label">RATING</div><div class="or-bar"><div class="or-fill" style="width:${bar}%;background:${rColor(a.overall)}"></div></div><div class="or-val" style="color:${rColor(a.overall)}">${a.overall}</div></div></div>`;
  }).join('');
}
function renderLeaderboard(teams){
  const ranked=teams.map(t=>({t,a:analyseTeam(t)})).map(({t,a})=>({name:t.name,color:t.color,budget:t.budget,players:t.players.length,rating:a?a.overall:0,avg:a?a.avg:0,xi:a?a.xi.length:0})).sort((a,b)=>b.rating-a.rating||b.avg-a.avg);
  const medals=['🥇','🥈','🥉'],maxR=Math.max(...ranked.map(r=>r.rating),1);
  const el=$id('leaderboard-wrap');if(!el)return;
  el.innerHTML=`<div class="lb-header"><div>#</div><div>TEAM</div><div>PLAYERS</div><div>AVG ⭐</div><div>SCORE</div></div>`+ranked.map((r,i)=>`<div class="lb-row${i<3?` rank-${i+1}`:''}" style="animation-delay:${i*.06}s"><div class="lb-rank${i<3?` r${i+1}`:''}"> ${i<3?medals[i]:i+1}</div><div class="lb-team"><span style="color:${r.color}">${r.name}</span><small>${fmt(r.budget)} left · ${r.xi} XI</small></div><div class="lb-stat">${r.players}</div><div class="lb-stat">${r.avg||'—'}</div><div class="lb-rating"><div class="rating-val" style="color:${rColor(r.rating)}">${r.rating||'—'}</div><div class="rating-bar"><div class="rating-fill" style="width:${Math.round(r.rating/maxR*100)}%;background:${rColor(r.rating)}"></div></div></div></div>`).join('');
}

/* ── Init ── */
// If already logged in from previous session, skip auth
if(currentUser){showScreen('screen-lobby');updateUserBadge();}

/* ══════════════════════════════════════
   SHAREABLE RESULT CARD (Canvas)
   ══════════════════════════════════════ */
function showMyResultCard(){
  if(!roomState) return;
  const me=roomState.teams.find(t=>t.sid===mySid);
  if(!me||!me.players.length){toast('You have no players to show!','error');return;}
  drawResultCard(me);
  $id('result-card-modal').classList.remove('hidden');
}
function closeResultCard(){ $id('result-card-modal').classList.add('hidden'); }
function downloadCard(){
  const canvas=$id('result-canvas');
  const a=document.createElement('a');
  a.download=`${myName || 'squad'}_ipl_auction.png`;
  a.href=canvas.toDataURL('image/png');
  a.click();
}

function drawResultCard(team){
  const W = 560;
  const ROW_H = 32, HDR_H = 22, SECTION_GAP = 10;
  const HEADER_AREA = 230; // fixed top section height
  const FOOTER_H = 36;
  const PAD = 28;

  // Fix pluralization
  const rolePlural = {
    'Batsman': 'BATSMEN',
    'Wicket-Keeper': 'WICKET-KEEPERS',
    'All-Rounder': 'ALL-ROUNDERS',
    'Bowler': 'BOWLERS',
  };
  const roleColors = {Batsman:'#E63946','Wicket-Keeper':'#06D6A0','All-Rounder':'#FFD700',Bowler:'#4D9FFF'};
  const roleEmojis = {Batsman:'🏏','Wicket-Keeper':'🧤','All-Rounder':'⚡',Bowler:'🎯'};
  const roleOrder  = ['Batsman','Wicket-Keeper','All-Rounder','Bowler'];

  // Group players
  const groups = {};
  roleOrder.forEach(r => groups[r] = []);
  team.players.forEach(p => { (groups[p.role] = groups[p.role]||[]).push(p); });

  // Calculate exact height needed
  let contentH = 0;
  roleOrder.forEach(role => {
    const ps = groups[role]||[];
    if(!ps.length) return;
    contentH += HDR_H + 6;          // role header
    contentH += ps.length * ROW_H;  // player rows
    contentH += SECTION_GAP;        // gap after section
  });

  const H = HEADER_AREA + contentH + FOOTER_H + 20;

  const canvas = $id('result-canvas');
  canvas.width  = W;
  canvas.height = H;
  // CSS scaling — keep card max 500px wide on screen
  canvas.style.width  = '100%';
  canvas.style.height = 'auto';

  const ctx = canvas.getContext('2d');

  // ── Background ──
  const bg = ctx.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, '#06080F');
  bg.addColorStop(1, '#0F1520');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  // ── Gold border ──
  ctx.strokeStyle = 'rgba(255,215,0,0.35)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.roundRect(8, 8, W-16, H-16, 14);
  ctx.stroke();

  // ── Subtle gold shimmer at top ──
  const shimmer = ctx.createLinearGradient(0, 0, 0, 120);
  shimmer.addColorStop(0, 'rgba(255,215,0,0.08)');
  shimmer.addColorStop(1, 'rgba(255,215,0,0)');
  ctx.fillStyle = shimmer;
  ctx.fillRect(8, 8, W-16, 120);

  // ── Trophy emoji ──
  ctx.font = '42px serif';
  ctx.textAlign = 'center';
  ctx.fillText('🏆', W/2, 60);

  // ── Title ──
  ctx.fillStyle = '#FFD700';
  ctx.font = 'bold 26px Impact, "Arial Narrow", sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('IPL MEGA AUCTION 2025', W/2, 96);

  // ── Team name ──
  ctx.fillStyle = team.color || '#e9c46a';
  ctx.font = 'bold 38px Impact, "Arial Narrow", sans-serif';
  ctx.fillText(team.name.toUpperCase(), W/2, 142);

  // ── Stats bar ──
  const barY = 158, barH = 50;
  ctx.fillStyle = 'rgba(255,255,255,0.07)';
  ctx.beginPath(); ctx.roundRect(PAD, barY, W-PAD*2, barH, 8); ctx.fill();
  ctx.strokeStyle = 'rgba(255,215,0,0.15)'; ctx.lineWidth = 1;
  ctx.stroke();

  const spent = 10000 - team.budget;
  const stats = [
    { label:'PLAYERS', val: String(team.players.length) },
    { label:'SPENT',   val: fmt(spent) },
    { label:'BUDGET',  val: fmt(team.budget) },
  ];
  const colW = (W - PAD*2) / 3;
  stats.forEach((s, i) => {
    const x = PAD + colW * i + colW/2;
    ctx.fillStyle = '#FFD700';
    ctx.font = 'bold 18px Impact, "Arial Narrow", sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(s.val, x, barY + 22);
    ctx.fillStyle = 'rgba(255,255,255,0.45)';
    ctx.font = '10px Arial, sans-serif';
    ctx.fillText(s.label, x, barY + 38);
  });

  // ── Divider ──
  const divY = barY + barH + 12;
  ctx.strokeStyle = 'rgba(255,215,0,0.25)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(PAD, divY); ctx.lineTo(W-PAD, divY); ctx.stroke();

  // ── Player groups ──
  let y = divY + 14;

  roleOrder.forEach(role => {
    const ps = groups[role]||[];
    if(!ps.length) return;

    const color = roleColors[role];
    const emoji = roleEmojis[role];
    const label = `${emoji} ${rolePlural[role]} (${ps.length})`;

    // Role header bg pill
    ctx.fillStyle = color + '22';
    ctx.beginPath(); ctx.roundRect(PAD, y, W-PAD*2, HDR_H, 5); ctx.fill();
    ctx.strokeStyle = color + '55'; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = color;
    ctx.font = 'bold 12px Arial, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(label, PAD + 10, y + 15);
    y += HDR_H + 6;

    ps.forEach((p, idx) => {
      // Alternate row shading
      ctx.fillStyle = idx % 2 === 0
        ? 'rgba(255,255,255,0.04)'
        : 'rgba(255,255,255,0.02)';
      ctx.beginPath(); ctx.roundRect(PAD, y, W-PAD*2, ROW_H - 2, 4); ctx.fill();

      // Player name
      ctx.fillStyle = '#E8EBF0';
      ctx.font = 'bold 14px Arial, sans-serif';
      ctx.textAlign = 'left';
      // Truncate long names
      let name = p.name;
      if(ctx.measureText(name).width > 320) {
        while(ctx.measureText(name + '…').width > 320 && name.length > 0) name = name.slice(0,-1);
        name += '…';
      }
      ctx.fillText(name, PAD + 10, y + 21);

      // Price
      ctx.fillStyle = '#FFD700';
      ctx.font = 'bold 13px Arial, sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(fmt(p.sold_price), W - PAD - 8, y + 21);

      y += ROW_H;
    });
    y += SECTION_GAP;
  });

  // ── Footer ──
  const footerY = H - FOOTER_H;
  ctx.fillStyle = 'rgba(255,215,0,0.08)';
  ctx.fillRect(0, footerY, W, FOOTER_H);
  ctx.strokeStyle = 'rgba(255,215,0,0.2)'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(0, footerY); ctx.lineTo(W, footerY); ctx.stroke();
  ctx.fillStyle = 'rgba(255,255,255,0.35)';
  ctx.font = '11px Arial, sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('🏏 ipl-auction25-3d.up.railway.app', W/2, footerY + 22);
}
