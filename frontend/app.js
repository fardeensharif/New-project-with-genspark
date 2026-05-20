/* =========================================================
   NIGHTWATCH-CAM frontend
   - Polls POST /api/step at ~6 Hz with current keys.
   - Keeps a "sanity" model that drives camera shake / glitches.
   - Simulates a Twitch-style chat that reacts to scares.
   - Uses the Web Speech API (when granted) to caption the user
     into the bottom-center subtitle bar AND forwards what they
     said as a `prompt` to the backend, which is how the world
     model gets steered ("I think there's someone in the alley...").
   ========================================================= */

(() => {
"use strict";

const $ = (s) => document.querySelector(s);
const feed     = $("#feed");
const ctx      = feed.getContext("2d");
const stage    = $("#stage");
const subtitle = $("#subtitle");
const chatLog  = $("#chat-log");
const ekg      = $("#ekg");
const ekgCtx   = ekg.getContext("2d");
const battFill = $("#batt-fill");
const battPct  = $("#batt-pct");
const bpmEl    = $("#bpm");
const viewersEl= $("#viewers");
const glitch   = $("#glitch");
const redflash = $("#redflash");
const bootEl   = $("#boot");
const startBtn = $("#start");
const backendInfo = $("#backend-info");

// --------------------------------------------------------
// State
// --------------------------------------------------------
const state = {
  keys: new Set(),
  lastDirection: "stop",
  pendingPrompt: "",     // last micro-chunk of speech to send next
  pendingEvent: "none",  // queued jump-scare for next /step
  sanity: 100,
  battery: 100,
  flashlightOn: true,
  bpm: 72,
  viewers: 0,
  running: false,
  frameInFlight: false,
  scareCooldown: 0,
};

// --------------------------------------------------------
// API
// --------------------------------------------------------
async function apiInfo() {
  const r = await fetch("/api/info");
  return r.json();
}
async function apiReset() {
  await fetch("/api/reset", { method: "POST" });
}
async function apiStep(direction, prompt, event) {
  const r = await fetch("/api/step", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ direction, prompt, event }),
  });
  if (!r.ok) throw new Error("step failed " + r.status);
  const blob = await r.blob();
  return blob;
}

// --------------------------------------------------------
// Input
// --------------------------------------------------------
const KEY_TO_DIR = {
  "w": "forward", "ArrowUp":    "forward",
  "s": "backward","ArrowDown":  "backward",
  "a": "left",    "ArrowLeft":  "left",
  "d": "right",   "ArrowRight": "right",
  "q": "look_up",
  "e": "look_down",
};

function currentDirection() {
  // Priority: forward/backward > left/right > look. Newest pressed wins.
  const order = ["forward","backward","left","right","look_up","look_down"];
  let chosen = "stop";
  for (const k of state.keys) {
    const d = KEY_TO_DIR[k];
    if (d) chosen = d;
  }
  return chosen;
}

window.addEventListener("keydown", (e) => {
  if (!state.running) return;
  if (e.key === "r" || e.key === "R") { hardReset(); return; }
  if (e.key === "f" || e.key === "F") { toggleFlashlight(); return; }
  if (e.key === " ") { e.preventDefault(); pushToTalk(true); return; }
  state.keys.add(e.key);
});
window.addEventListener("keyup", (e) => {
  if (e.key === " ") { pushToTalk(false); return; }
  state.keys.delete(e.key);
});

// --------------------------------------------------------
// Speech -> subtitles + prompt steering
// --------------------------------------------------------
let recog = null;
let recogActive = false;

function setupSpeech() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  const r = new SR();
  r.continuous = true;
  r.interimResults = true;
  r.lang = "en-US";
  r.onresult = (ev) => {
    let text = "";
    for (let i = ev.resultIndex; i < ev.results.length; i++) {
      text += ev.results[i][0].transcript;
    }
    text = text.trim();
    if (!text) return;
    showSubtitle(text);
    state.pendingPrompt = text.slice(-220);
    // Did the streamer trigger a scare cue?
    maybeQueueScareFromSpeech(text);
  };
  r.onerror = () => {};
  r.onend = () => { if (recogActive) try { r.start(); } catch(_){} };
  return r;
}

function pushToTalk(active) {
  if (!recog) return;
  if (active) {
    recogActive = true;
    try { recog.start(); } catch(_) {}
    showSubtitle("● recording…", 800);
  } else {
    recogActive = false;
    try { recog.stop(); } catch(_) {}
  }
}

let subtitleTimer = null;
function showSubtitle(text, ttl = 2400) {
  subtitle.textContent = text;
  subtitle.classList.add("show");
  clearTimeout(subtitleTimer);
  subtitleTimer = setTimeout(() => subtitle.classList.remove("show"), ttl);
}

// Listen for "trigger words" the streamer says
const SCARE_WORDS = [
  { rx: /(someone|figure|person|man|woman) (in|at|down|near)/i, ev: "figure" },
  { rx: /\b(child|kid|girl|boy)\b/i, ev: "child" },
  { rx: /\b(shadow|something moving)\b/i, ev: "shadow" },
  { rx: /\b(hand|fingers)\b/i, ev: "hand" },
];
function maybeQueueScareFromSpeech(text) {
  if (state.scareCooldown > 0) return;
  for (const { rx, ev } of SCARE_WORDS) {
    if (rx.test(text)) {
      triggerScare(ev);
      return;
    }
  }
}

// --------------------------------------------------------
// Jump-scares
// --------------------------------------------------------
function triggerScare(eventName) {
  state.pendingEvent = eventName;
  state.scareCooldown = 60; // ~10 seconds at 6 Hz step rate
  state.sanity = Math.max(0, state.sanity - 22);
  // viewer count spike
  state.viewers += Math.floor(180 + Math.random() * 320);
  // chat explodes
  spamChat([
    "RUN!!!", "WTF IS THAT", "DUDE NO", "behind you", "GET OUT",
    "I'm calling the police", "i can't watch", "don't go closer",
    "WHO IS THAT??", "yo this is real", "TURN AROUND",
  ], 14);
  // visual fx
  redflash.classList.add("fire");
  setTimeout(() => redflash.classList.remove("fire"), 140);
  glitch.classList.add("active");
  setTimeout(() => glitch.classList.remove("active"), 1200);
  // flashlight flicker
  flickerFlashlight();
}

function flickerFlashlight() {
  let n = 8;
  const id = setInterval(() => {
    state.flashlightOn = !state.flashlightOn;
    if (--n <= 0) { clearInterval(id); state.flashlightOn = true; }
  }, 70);
}

function toggleFlashlight() {
  state.flashlightOn = !state.flashlightOn;
  // toggling drains a chunk of battery
  state.battery = Math.max(0, state.battery - 1);
}

// --------------------------------------------------------
// Chat simulator
// --------------------------------------------------------
const USERNAMES = [
  "ghoulhunter22","midnight_mara","skellington","pixelvampire",
  "lurker_404","empty_alley","nightowl","creepywatcher",
  "ouija_chad","mothmanFan","deadby2am","silenceofthecams",
  "wendigo_lover","oh_no_oh_no","streampossessed","ghastly99",
];
const AMBIENT = [
  "this place is creepy af",
  "go inside the house",
  "dude turn around",
  "the fog is so thick",
  "is that a streetlamp or a person??",
  "SHHH listen",
  "i don't like this",
  "subbed for 6 months 🩸",
  "lower the flashlight",
  "you sure you wanna go that way?",
  "did you hear that",
  "this is better than insidious",
  "100k gang where you at",
  "F in chat",
  "the buildings keep changing wtf",
  "look up",
  "go left",
  "DON'T GO LEFT",
];

function chatLine(user, msg) {
  const div = document.createElement("div");
  div.className = "msg";
  const u = document.createElement("span");
  u.className = "u u-c" + (1 + (hash(user) % 8));
  u.textContent = user + ":";
  div.appendChild(u);
  div.append(" " + msg);
  chatLog.appendChild(div);
  // Trim to ~12 lines
  while (chatLog.children.length > 14) chatLog.removeChild(chatLog.firstChild);
}
function hash(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return h; }

function spamChat(pool, n) {
  for (let i = 0; i < n; i++) {
    setTimeout(() => {
      const u = USERNAMES[Math.floor(Math.random() * USERNAMES.length)];
      const m = pool[Math.floor(Math.random() * pool.length)];
      chatLine(u, m);
    }, i * 90);
  }
}

function ambientChatTick() {
  if (Math.random() < 0.55) {
    const u = USERNAMES[Math.floor(Math.random() * USERNAMES.length)];
    const m = AMBIENT[Math.floor(Math.random() * AMBIENT.length)];
    chatLine(u, m);
  }
}

// --------------------------------------------------------
// Sanity / EKG / battery / viewers HUD
// --------------------------------------------------------
const ekgBuf = new Array(ekg.width).fill(20);
let ekgPhase = 0;

function drawEKG() {
  ekgCtx.clearRect(0, 0, ekg.width, ekg.height);
  // grid
  ekgCtx.strokeStyle = "rgba(255,40,60,0.15)";
  ekgCtx.lineWidth = 1;
  for (let x = 0; x < ekg.width; x += 30) {
    ekgCtx.beginPath(); ekgCtx.moveTo(x, 0); ekgCtx.lineTo(x, ekg.height); ekgCtx.stroke();
  }
  // waveform
  ekgCtx.strokeStyle = state.sanity < 30 ? "#ff3040" : "#ff6070";
  ekgCtx.lineWidth = 2;
  ekgCtx.shadowColor = "#ff2030";
  ekgCtx.shadowBlur = 6;
  ekgCtx.beginPath();
  for (let x = 0; x < ekg.width; x++) {
    const y = ekg.height/2 - ekgBuf[x];
    if (x === 0) ekgCtx.moveTo(x, y); else ekgCtx.lineTo(x, y);
  }
  ekgCtx.stroke();
  ekgCtx.shadowBlur = 0;
}

function pushEKG() {
  // shift left
  ekgBuf.shift();
  // pulse cadence depends on bpm; tighter ekg the lower sanity
  ekgPhase += 0.08 + (100 - state.sanity) * 0.0009;
  let v = Math.sin(ekgPhase * 2) * 2;
  // spike
  const period = Math.max(8, 60 - Math.floor((100 - state.sanity) * 0.4));
  if (ekgBuf.length % period === 0) {
    ekgBuf.push(18); // skipped one shift but we'll re-shift below
  }
  // generate next sample: occasional sharp spike
  const t = Date.now() * 0.001;
  const spike = Math.sin(t * (1 + (100-state.sanity)*0.03)) > 0.985 ? 18 : 0;
  v += spike;
  ekgBuf.push(v + (Math.random()-0.5)*1.2);
}

function updateBattery() {
  // flashlight on drains; off recovers slowly
  if (state.flashlightOn) state.battery -= 0.04;
  else state.battery += 0.02;
  state.battery = Math.max(0, Math.min(100, state.battery));
  battFill.style.width = state.battery.toFixed(1) + "%";
  battPct.textContent = Math.round(state.battery);
}

function updateBPM() {
  const target = 72 + Math.round((100 - state.sanity) * 0.9) + Math.round(Math.random() * 4);
  state.bpm += (target - state.bpm) * 0.1;
  bpmEl.textContent = Math.round(state.bpm);
}

function updateViewers() {
  // gentle drift toward base, faster spike decay
  const base = 248;
  state.viewers += (base - state.viewers) * 0.005 + (Math.random() - 0.4) * 2;
  state.viewers = Math.max(0, state.viewers);
  viewersEl.textContent = Math.round(state.viewers).toLocaleString();
}

function updateGlobalGlitch() {
  if (state.sanity < 35) stage.classList.add("shake");
  else stage.classList.remove("shake");
  if (state.sanity < 50 && Math.random() < 0.02) {
    glitch.classList.add("active");
    setTimeout(() => glitch.classList.remove("active"), 250);
  }
}

// --------------------------------------------------------
// Render loop  (HUD ticks ~30 Hz, frame fetch ~6 Hz)
// --------------------------------------------------------
function hudTick() {
  pushEKG();
  drawEKG();
  updateBattery();
  updateBPM();
  updateViewers();
  updateGlobalGlitch();
  if (state.scareCooldown > 0) state.scareCooldown -= 1;
  // sanity slowly recovers when the world is quiet
  if (state.scareCooldown <= 0)
    state.sanity = Math.min(100, state.sanity + 0.05);
  // dark areas drain sanity slightly
  if (state.lastDirection === "forward")
    state.sanity = Math.max(0, state.sanity - 0.03);
}

let frameImg = new Image();
async function frameTick() {
  if (!state.running || state.frameInFlight) return;
  state.frameInFlight = true;

  const dir = currentDirection();
  state.lastDirection = dir;
  const prompt = state.pendingPrompt; state.pendingPrompt = "";
  const event = state.pendingEvent;   state.pendingEvent = "none";

  try {
    const blob = await apiStep(dir, prompt, event);
    const url = URL.createObjectURL(blob);
    await new Promise((res, rej) => {
      frameImg.onload = res;
      frameImg.onerror = rej;
      frameImg.src = url;
    });
    drawFrame(frameImg);
    URL.revokeObjectURL(url);
  } catch (e) {
    console.warn("step error", e);
  } finally {
    state.frameInFlight = false;
  }
}

function drawFrame(img) {
  // Letter/pillarbox to canvas size, then dim if flashlight is off.
  ctx.save();
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, feed.width, feed.height);
  const ar = img.width / img.height;
  const car = feed.width / feed.height;
  let dw, dh;
  if (ar > car) { dw = feed.width; dh = feed.width / ar; }
  else          { dh = feed.height; dw = feed.height * ar; }
  ctx.drawImage(img, (feed.width - dw)/2, (feed.height - dh)/2, dw, dh);

  // Flashlight off -> heavy darken + tiny ambient cone
  if (!state.flashlightOn || state.battery < 1) {
    ctx.fillStyle = "rgba(0,0,0,0.92)";
    ctx.fillRect(0, 0, feed.width, feed.height);
    // tiny ambient light from streetlamp
    const grad = ctx.createRadialGradient(
      feed.width/2, feed.height*0.42, 5,
      feed.width/2, feed.height*0.42, 90
    );
    grad.addColorStop(0, "rgba(255,170,80,0.22)");
    grad.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, feed.width, feed.height);
  }
  ctx.restore();
}

// --------------------------------------------------------
// Boot
// --------------------------------------------------------
async function hardReset() {
  await apiReset();
  state.sanity = 100;
  state.battery = 100;
  state.bpm = 72;
  state.viewers = 220 + Math.floor(Math.random() * 60);
  state.scareCooldown = 0;
  state.pendingEvent = "none";
  chatLog.innerHTML = "";
}

async function start() {
  // hide boot, kick everything on
  bootEl.classList.add("hidden");
  state.running = true;
  state.viewers = 220 + Math.floor(Math.random() * 60);

  await apiReset();

  recog = setupSpeech();
  if (recog) {
    showSubtitle("press SPACE to talk", 2200);
  } else {
    showSubtitle("(mic unavailable - no subtitles)", 2200);
  }

  // seed chat
  spamChat(["just got here", "ohh new stream", "hi mods", "scary content gang", "is this AI generated?"], 6);
}

async function init() {
  try {
    const info = await apiInfo();
    backendInfo.textContent =
      info.backend === "hyworld"
        ? `tencent/HY-World-2.0 on ${info.device}`
        : "MOCK adapter (procedural — set WORLD_BACKEND=hyworld on a GPU host)";
  } catch (e) {
    backendInfo.textContent = "(api unreachable)";
  }
  startBtn.addEventListener("click", start);

  // Tick loops
  setInterval(hudTick, 33);             // ~30 Hz HUD
  setInterval(frameTick, 160);          // ~6 Hz world step
  setInterval(ambientChatTick, 1100);   // background chatter
}

init();
})();
