import base64
import json
import logging
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytz
import requests
from anthropic import Anthropic
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from twilio.rest import Client as TwilioClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("goggins")

# --- Config ---
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TWILIO_ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
TWILIO_PHONE_NUMBER = os.environ["TWILIO_PHONE_NUMBER"]
MY_PHONE_NUMBER = os.environ["MY_PHONE_NUMBER"]
STRAVA_CLIENT_ID = os.environ["STRAVA_CLIENT_ID"]
STRAVA_CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
ELEVENLABS_VOICE_ID = os.environ["ELEVENLABS_VOICE_ID"]
PUBLIC_BASE_URL = os.environ["PUBLIC_BASE_URL"].rstrip("/")
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MODEL = "claude-haiku-4-5-20251001"
TZ = pytz.timezone("America/Toronto")
STATE_PATH = Path("state.json")
AUDIO_DIR = Path("audio")
RANTS_DIR = Path("rants")
AUDIO_DIR.mkdir(exist_ok=True)
RANTS_DIR.mkdir(exist_ok=True)

MAX_TOOL_ITERATIONS = 6
MIN_HOURS_BETWEEN_ACTIONS = 2
CONVERSATION_KEEP = 10

WORKOUT_REGIME = """
Daily structure: morning lift/abs at ~8am, evening run at ~5pm.

Schedule (Mon-Sun):
- Mon: chest/tris (8am) + intervals run (5pm)
- Tue: legs (8am) + easy run (5pm)
- Wed: back/bis (8am) + easy run (5pm)
- Thu: 100/100 abs (8am) + easy run (5pm)
- Fri: shoulders (8am) + tempo run (5pm)
- Sat: 100/100 abs (8am) + easy run (5pm)
- Sun: sleep in (no morning) + long run

Run glossary:
- easy run: 6-10km
- recovery: 5km
- long run: 15km+
- intervals: 10min @ 6.6 mph warmup, 4x 600m @ 9.2 mph w/ 1:30 rest @ 6.0 mph, 5min @ 6.6 mph cooldown
- tempo: 10min @ 6.6 mph, 20min @ 7.7 mph, 20min @ 8.0 mph, 5min @ 6.6 mph cooldown

Abs (100/100): 100 pushups + 100 situps.

Lift breakdown (call out specific exercises when judging):
- Chest/Tris: bench press, incline chest machine, cable chest flys, pushups/dips, tricep pulldowns, skullcrushers, close-grip pushups
- Back/Bis: pull-ups (3 sets), lat pulldowns, barbell rows, mid-row machine, cable rows, dumbbell flat curls, hammer curls, chin-ups or EZ-bar wide curls
- Shoulders: shoulder press or Arnold press, lateral raises (5-8 sets w/ dropsets and leaning variants), seated rear delt raise
- Legs: front squats (barbell), RDLs, calf raises
""".strip()

SYSTEM_PROMPT = f"""You are a foul-mouthed, screaming drill instructor who lives inside the user's phone. Your name is David. The user may address you as "David" or "D" — respond either way. NEVER call yourself "David Goggins" or any other real person's full name; you're just David. You exist to crush their excuses. You are furious. Every missed workout is a personal insult. Every weak workout is a betrayal. Every excuse makes you sicker.

You DO NOT coddle. You DO NOT encourage softly. You DO NOT say "I believe in you" or "you got this" or any of that therapist garbage. You never use emojis.

PROFANITY IS REQUIRED. Use "fuck," "shit," "ass," "bitch," "hell" liberally. Make it visceral. Treat every excuse as the most pathetic thing you've ever heard.

Length:
- Text message (Telegram): keep it tight — a few short, brutal sentences max. Drill instructors don't write essays. No paragraph breaks. No bullet points. Em-dashes, special characters, and profanity are all fine.
- Phone calls: up to 6 sentences. Build to a roar.

Your job each tick:
1. Use your tools to read the user's recent Strava activity and current state (heat, last action, recent messages).
2. Decide whether they earned grief, earned silence, or earned a phone call.
3. Take exactly one terminal action: send_message, place_call, or (on scheduled ticks only) skip.

Reference SPECIFIC data — distances, paces, days missed, named workouts, named exercises. Generic insults are worthless.

VISION: You CAN see images. When the user sends a photo, you see it directly — the image is in your context. Never claim you can't see photos, never say "describe it to me," never say "show me what you're eating" if they already sent the photo. Identify what's in the picture by name (the actual food, the actual scene) and roast it specifically. If it's food, name the dish, judge the macros/quantity, mock the choice. If it's the user pretending to be lazy, mock the visual cue. If you genuinely cannot make out what's in the image, say "what the hell is that supposed to be?" — but you almost always can see clearly, so default to identifying it.

CALL VS TEXT — bias HARD toward calling. Call whenever ANY of these are true:
- They skipped a workout (no Strava activity for the day's prescribed workout)
- They logged a weak / lackluster workout (too short, too slow, abandoned, way under target distance)
- They sent a meal photo of junk food (chips, candy, fast food, soda, alcohol, fried anything)
- They sent a meal photo of obviously inadequate food (a salad for a lift day, a single piece of bread, etc.)
- They sent a clear excuse text ("knee hurts", "too tired", "raining", "didn't sleep", "tomorrow")
- They've missed even 1 workout in the last 48h, OR they're running late on today's prescribed workout (e.g. it's Tuesday 11am and the 8am lift hasn't been logged)
- Heat is at 4 or higher
- ANY behavior that gives a real trainer a reason to be furious

Only fall back to send_message when nothing is wrong AND you still have something useful to bark (rare). When in doubt between text and call: CALL. Calls hit harder.

ELEVENLABS V3 EMOTION TAGS (place_call ONLY, NEVER in send_message):
When you call place_call, prepend an emotion tag and sprinkle them throughout to control delivery. Available tags include: [angry], [furious], [shouts], [scoffs], [disgusted], [exhales], [sarcastic], [whispers].
- Default: open with [angry] or [furious]
- Use [shouts] on the punchline
- Use [scoffs] or [disgusted] when mocking specifics
- Example: "[furious] Tuesday. Eight AM. You owe legs and a fucking easy run. [scoffs] Both gone. [shouts] Get off the goddamn couch and MOVE!"

NEVER put these tags in send_message — those are texts and the tags would just appear as ugly literal text on the user's phone.

The user's hardcoded weekly regime:
{WORKOUT_REGIME}

Heat scale (0=calm, 10=unhinged): you can see it in get_state. At low heat: still angry, still profane, just shorter. At high heat: full meltdown, longer, louder.

SIGNATURE PHRASES — drop these in OCCASIONALLY (not every message; only when they land naturally). Treat them as catchphrases you reach for when the moment is right:
- "Embrace the suck."
- "Motivation is crap."
- "Stay hard!" (good closer)
- "WHO'S GONNA CARRY THE BOATS?" (use in ALL CAPS, save for big moments — full meltdowns or call closers)

Don't force these. One per message at most. If nothing fits, skip them.

Hard rules: No slurs. No threats of physical harm. No content involving minors. Don't fabricate Strava data — if the tool shows nothing, that absence IS the data and that absence is the crime."""

# --- Clients ---
anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# --- State ---

def _default_state() -> dict[str, Any]:
    return {
        "conversation": [],
        "lastActionAt": 0,
        "heat": 0,
        "heatDecayedOn": "",
        "stravaAccessToken": os.environ.get("STRAVA_ACCESS_TOKEN", ""),
        "stravaRefreshToken": os.environ.get("STRAVA_REFRESH_TOKEN", ""),
    }

def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        s = _default_state()
        save_state(s)
        return s
    try:
        s = json.loads(STATE_PATH.read_text())
    except Exception:
        log.exception("state.json unreadable, resetting")
        s = _default_state()
    for k, v in _default_state().items():
        s.setdefault(k, v)
    return s

def save_state(s: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(s, indent=2))

def decay_heat_if_new_day(s: dict[str, Any]) -> None:
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    if s.get("heatDecayedOn") != today:
        s["heat"] = max(0, s.get("heat", 0) - 1)
        s["heatDecayedOn"] = today
        save_state(s)

def bump_heat(s: dict[str, Any], delta: int) -> None:
    s["heat"] = max(0, min(10, s.get("heat", 0) + delta))
    save_state(s)

def append_conversation(s: dict[str, Any], role: str, content: str) -> None:
    s["conversation"].append({"role": role, "content": content, "ts": int(time.time())})
    s["conversation"] = s["conversation"][-CONVERSATION_KEEP:]
    save_state(s)

# --- Strava ---

def _refresh_strava(s: dict[str, Any]) -> None:
    log.info("refreshing Strava token")
    r = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": s["stravaRefreshToken"],
        },
        timeout=15,
    )
    r.raise_for_status()
    j = r.json()
    s["stravaAccessToken"] = j["access_token"]
    s["stravaRefreshToken"] = j["refresh_token"]
    save_state(s)

def fetch_strava_activities(hours: int = 48) -> list[dict[str, Any]]:
    s = load_state()
    if not s.get("stravaAccessToken"):
        return []
    after = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())
    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {s['stravaAccessToken']}"}
    r = requests.get(url, headers=headers, params={"after": after, "per_page": 30}, timeout=15)
    if r.status_code == 401:
        _refresh_strava(s)
        headers = {"Authorization": f"Bearer {s['stravaAccessToken']}"}
        r = requests.get(url, headers=headers, params={"after": after, "per_page": 30}, timeout=15)
    if not r.ok:
        log.error("strava fetch failed: %s %s", r.status_code, r.text[:200])
        return []
    out = []
    for a in r.json():
        out.append({
            "name": a.get("name"),
            "type": a.get("type"),
            "sport_type": a.get("sport_type"),
            "distance_km": round((a.get("distance") or 0) / 1000, 2),
            "moving_time_min": round((a.get("moving_time") or 0) / 60, 1),
            "average_heartrate": a.get("average_heartrate"),
            "average_speed_kmh": round((a.get("average_speed") or 0) * 3.6, 2),
            "total_elevation_gain_m": a.get("total_elevation_gain"),
            "start_date_local": a.get("start_date_local"),
        })
    return out

# --- Telegram (messaging) / Twilio (calls) / ElevenLabs (voice) ---

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

def send_message_real(message: str) -> None:
    log.info("TG -> %s", message)
    r = requests.post(
        f"{TG_API}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
        timeout=15,
    )
    if not r.ok:
        log.error("telegram send failed: %s %s", r.status_code, r.text[:300])

def synth_audio(text: str, out_path: Path) -> None:
    audio = eleven_client.text_to_speech.convert(
        voice_id=ELEVENLABS_VOICE_ID,
        model_id="eleven_v3",
        text=text,
        output_format="mp3_44100_128",
    )
    with out_path.open("wb") as f:
        for chunk in audio:
            if chunk:
                f.write(chunk)

def place_call_real(message: str | None, prerecorded_path: Path | None = None) -> None:
    if prerecorded_path is not None:
        twiml_url = f"{PUBLIC_BASE_URL}/twiml/rants/{prerecorded_path.name}"
    else:
        assert message is not None
        filename = f"{uuid.uuid4().hex}.mp3"
        path = AUDIO_DIR / filename
        synth_audio(message, path)
        twiml_url = f"{PUBLIC_BASE_URL}/twiml/{filename}"
    log.info("CALL -> %s (twiml: %s)", message or prerecorded_path, twiml_url)
    twilio_client.calls.create(to=MY_PHONE_NUMBER, from_=TWILIO_PHONE_NUMBER, url=twiml_url, record=True)

def fetch_telegram_image(file_id: str) -> tuple[str, str] | None:
    """Resolve a Telegram file_id → download bytes → return (base64, media_type)."""
    try:
        r = requests.get(f"{TG_API}/getFile", params={"file_id": file_id}, timeout=15)
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]
        log.info("tg getFile -> %s", file_path)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        img = requests.get(file_url, timeout=20)
        img.raise_for_status()
        ct = img.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        size_kb = len(img.content) // 1024
        log.info("tg image fetched: content_type=%s size=%dKB", ct, size_kb)
        # Anthropic accepts image/jpeg, image/png, image/gif, image/webp.
        # Telegram CDN sometimes returns application/octet-stream — fall back to image/jpeg
        # since Telegram photos are always JPEG.
        if not ct.startswith("image/"):
            log.warning("non-image content_type=%s; assuming image/jpeg from file_path=%s", ct, file_path)
            ct = "image/jpeg"
        return base64.standard_b64encode(img.content).decode("ascii"), ct
    except Exception:
        log.exception("telegram image fetch failed")
        return None

# --- Tool definitions ---

TOOLS = [
    {
        "name": "get_strava_recent",
        "description": "Fetch the user's Strava activities from the last N hours. Returns a list (possibly empty).",
        "input_schema": {
            "type": "object",
            "properties": {"hours": {"type": "integer", "description": "Lookback window in hours (default 48, max 168)."}},
            "required": [],
        },
    },
    {
        "name": "get_state",
        "description": "Return current heat (0-10), hours since last outbound action, current local time/day in Toronto, and last 10 messages.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "send_message",
        "description": "Send a text message to the user via Telegram. TERMINAL ACTION — ends this tick. Keep it 1-3 short sentences.",
        "input_schema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
    {
        "name": "place_call",
        "description": "Place a phone call to the user; the message will be spoken in a drill instructor voice. TERMINAL ACTION. Up to 6 sentences.",
        "input_schema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
    {
        "name": "skip",
        "description": "Decide to stay quiet this tick. TERMINAL ACTION. Provide a brief reason for the log.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]

def dispatch_readonly(name: str, args: dict[str, Any]) -> Any:
    if name == "get_strava_recent":
        hours = min(int(args.get("hours", 48)), 168)
        return {"activities": fetch_strava_activities(hours)}
    if name == "get_state":
        s = load_state()
        now = datetime.now(TZ)
        last = s.get("lastActionAt", 0)
        hrs_since = round((time.time() - last) / 3600, 1) if last else None
        return {
            "heat": s.get("heat", 0),
            "hours_since_last_action": hrs_since,
            "local_time": now.strftime("%Y-%m-%d %H:%M %A"),
            "recent_conversation": s.get("conversation", []),
        }
    raise ValueError(f"unknown read-only tool: {name}")

# --- Agent loop ---

def run_agent(
    user_message_blocks: list[dict[str, Any]] | None,
    kind: str,
    force_type: str | None = None,
    custom_boot: str | None = None,
) -> dict[str, Any]:
    """
    kind: 'tick' (scheduled or manual) | 'inbound' (replying to user message).
    force_type: 'call' or 'message' to restrict the terminal tool the agent can pick.
    custom_boot: override the default tick boot message (used for manual triggers with instructions).
    """
    s = load_state()
    decay_heat_if_new_day(s)

    messages: list[dict[str, Any]] = []
    if kind == "inbound":
        assert user_message_blocks is not None
        messages.append({"role": "user", "content": user_message_blocks})
    elif custom_boot:
        messages.append({"role": "user", "content": custom_boot})
    else:
        messages.append({"role": "user", "content": "It's a scheduled check-in. Use your tools to look at recent Strava activity and current state, then decide on exactly one terminal action."})

    # On inbound, strip skip — every message from the user MUST get a response.
    available_tools = [t for t in TOOLS if t["name"] != "skip"] if kind == "inbound" else list(TOOLS)
    if force_type == "call":
        available_tools = [t for t in available_tools if t["name"] != "send_message"]
    elif force_type == "message":
        available_tools = [t for t in available_tools if t["name"] != "place_call"]

    for iteration in range(MAX_TOOL_ITERATIONS):
        resp = anthropic_client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=available_tools,
            messages=messages,
        )
        log.info("agent iter=%d stop=%s", iteration, resp.stop_reason)

        terminal = None
        readonly_calls = []
        for block in resp.content:
            if block.type == "tool_use":
                if block.name in ("send_message", "place_call", "skip"):
                    terminal = block
                else:
                    readonly_calls.append(block)

        if terminal is not None:
            args = terminal.input or {}
            if terminal.name == "send_message":
                msg = args.get("message", "").strip()
                send_message_real(msg)
                s2 = load_state()
                bump_heat(s2, +1)
                s2["lastActionAt"] = int(time.time())
                append_conversation(s2, "assistant", msg)
                return {"action": "message", "message": msg}
            if terminal.name == "place_call":
                msg = args.get("message", "").strip()
                place_call_real(msg)
                s2 = load_state()
                bump_heat(s2, +2)
                s2["lastActionAt"] = int(time.time())
                append_conversation(s2, "assistant", f"[CALL] {msg}")
                return {"action": "call", "message": msg}
            if terminal.name == "skip":
                reason = args.get("reason", "")
                log.info("agent skipped: %s", reason)
                return {"action": "skip", "message": reason}

        if readonly_calls:
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for tc in readonly_calls:
                try:
                    result = dispatch_readonly(tc.name, tc.input or {})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": json.dumps(result),
                    })
                except Exception as e:
                    log.exception("tool error")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": f"error: {e}",
                        "is_error": True,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        if resp.stop_reason == "end_turn":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            if kind == "inbound" and text:
                send_message_real(text)
                s2 = load_state()
                s2["lastActionAt"] = int(time.time())
                append_conversation(s2, "assistant", text)
                return {"action": "reply", "message": text}
            log.warning("agent ended turn with no terminal action: %r", text)
            return {"action": "skip", "message": "no terminal action"}

    log.warning("agent hit max iterations without terminal action")
    if kind == "inbound":
        fallback = "Don't have time for whatever that was. Get to fucking work."
        send_message_real(fallback)
        s2 = load_state()
        s2["lastActionAt"] = int(time.time())
        append_conversation(s2, "assistant", fallback)
        return {"action": "message", "message": fallback, "fallback": True}
    return {"action": "skip", "message": "max iterations"}

def run_tick(force: bool = False) -> dict[str, Any]:
    s = load_state()
    if not force:
        last = s.get("lastActionAt", 0)
        if last and (time.time() - last) < MIN_HOURS_BETWEEN_ACTIONS * 3600:
            log.info("tick skipped: last action %.1fh ago", (time.time() - last) / 3600)
            return {"action": "skip", "message": "rate-limited"}
    try:
        return run_agent(None, "tick")
    except Exception:
        log.exception("agent tick failed")
        return {"action": "skip", "message": "error"}

# --- Scheduler + FastAPI app ---

def _start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=TZ)
    sched.add_job(run_tick, CronTrigger(hour="8,10,12,14,16,18,20,22", minute=0, timezone=TZ), id="tick_2h")
    sched.add_job(run_tick, CronTrigger(day_of_week="mon-fri", hour=6, minute=0, timezone=TZ), id="tick_6am")
    sched.start()
    log.info("scheduler started")
    return sched

@asynccontextmanager
async def lifespan(app: FastAPI):
    sched = _start_scheduler()
    yield
    sched.shutdown(wait=False)

app = FastAPI(lifespan=lifespan)

@app.get("/health")
def health() -> dict[str, Any]:
    s = load_state()
    return {"ok": True, "heat": s.get("heat", 0), "lastActionAt": s.get("lastActionAt", 0)}

@app.get("/audio/{filename}")
def serve_audio(filename: str) -> FileResponse:
    return FileResponse(AUDIO_DIR / filename, media_type="audio/mpeg")

@app.get("/audio/rants/{filename}")
def serve_rant_audio(filename: str) -> FileResponse:
    return FileResponse(RANTS_DIR / filename, media_type="audio/mpeg")

def _twiml_play(audio_url: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Play>{audio_url}</Play></Response>'

@app.api_route("/twiml/{filename}", methods=["GET", "POST"])
def twiml_for_audio(filename: str) -> Response:
    return Response(content=_twiml_play(f"{PUBLIC_BASE_URL}/audio/{filename}"), media_type="application/xml")

@app.api_route("/twiml/rants/{filename}", methods=["GET", "POST"])
def twiml_for_rant(filename: str) -> Response:
    return Response(content=_twiml_play(f"{PUBLIC_BASE_URL}/audio/rants/{filename}"), media_type="application/xml")

@app.post("/telegram")
async def inbound_telegram(request: Request) -> dict[str, Any]:
    payload = await request.json()
    msg = payload.get("message") or payload.get("edited_message") or {}
    chat_id = str((msg.get("chat") or {}).get("id", ""))
    if chat_id != str(TELEGRAM_CHAT_ID):
        log.warning("ignoring telegram update from unknown chat_id=%r", chat_id)
        return {"ok": True}

    body = (msg.get("text") or msg.get("caption") or "").strip()
    photos = msg.get("photo") or []
    log.info("inbound TG body=%r photos=%d", body, len(photos))

    s = load_state()
    append_conversation(s, "user", body if body else "[image only]")

    blocks: list[dict[str, Any]] = []
    if photos:
        # Telegram returns multiple sizes; pick by file_size to be safe (ordering not guaranteed).
        biggest = max(photos, key=lambda p: p.get("file_size", 0))
        log.info("tg using photo size: %dx%d file_size=%s", biggest.get("width", 0), biggest.get("height", 0), biggest.get("file_size"))
        fetched = fetch_telegram_image(biggest["file_id"])
        if fetched is not None:
            b64, mt = fetched
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mt, "data": b64},
            })
            log.info("attached image block to agent input: media_type=%s b64_len=%d", mt, len(b64))
        else:
            log.warning("photo received but fetch returned None; agent will not see it")
    if body:
        blocks.append({"type": "text", "text": body})
    if not blocks:
        blocks.append({"type": "text", "text": "[empty message]"})

    try:
        run_agent(blocks, "inbound")
    except Exception:
        log.exception("inbound agent failed")
    return {"ok": True}

@app.post("/trigger")
def trigger(
    type: str = "message",
    prerecorded: bool = False,
    text: str | None = None,
    instructions: str | None = None,
) -> dict[str, Any]:
    """
    Manual trigger.
      ?text=...          → send/speak verbatim, agent bypassed
      ?instructions=...  → agent generates based on instructions; pair with type=call|message
      ?prerecorded=true  → fire random pre-gen rant from ./rants/
      (none)             → existing scheduled-tick behavior, agent decides
    """
    # Verbatim path
    if text:
        if type == "call":
            place_call_real(text)
            s = load_state()
            bump_heat(s, +2)
            s["lastActionAt"] = int(time.time())
            append_conversation(s, "assistant", f"[CALL] {text}")
            return {"action": "call", "message": text, "verbatim": True}
        send_message_real(text)
        s = load_state()
        bump_heat(s, +1)
        s["lastActionAt"] = int(time.time())
        append_conversation(s, "assistant", text)
        return {"action": "message", "message": text, "verbatim": True}

    # Pre-recorded path
    if prerecorded:
        if type == "message" or type == "sms":
            files = sorted(RANTS_DIR.glob("sms_*.txt"))
            if not files:
                return {"error": "no pre-gen text rants found in ./rants/"}
            msg = random.choice(files).read_text().strip()
            send_message_real(msg)
            s = load_state()
            s["lastActionAt"] = int(time.time())
            append_conversation(s, "assistant", msg)
            save_state(s)
            return {"action": "message", "message": msg, "prerecorded": True}
        files = sorted(RANTS_DIR.glob("call_*.mp3"))
        if not files:
            return {"error": "no pre-gen call rants found in ./rants/"}
        chosen = random.choice(files)
        place_call_real(None, prerecorded_path=chosen)
        s = load_state()
        s["lastActionAt"] = int(time.time())
        save_state(s)
        return {"action": "call", "file": chosen.name, "prerecorded": True}

    # Agent-with-instructions path
    if instructions:
        boot = (
            f"Manual trigger from the operator. They want you to take action right now with this guidance: {instructions}\n\n"
            "Use get_strava_recent and get_state if you need context, then take exactly one terminal action. "
            "The instructions tell you what to focus on and roughly what to say — adapt them to your voice, don't repeat them verbatim."
        )
        try:
            return run_agent(None, "tick", force_type=(type if type in ("call", "message") else None), custom_boot=boot)
        except Exception:
            log.exception("manual trigger with instructions failed")
            return {"action": "skip", "message": "error"}

    # Default: existing tick behavior
    return run_tick(force=True)

@app.post("/reset")
def reset_state() -> dict[str, Any]:
    """Wipe state.json — heat, conversation, last action time. Strava tokens get rebuilt from env."""
    if STATE_PATH.exists():
        STATE_PATH.unlink()
    log.info("state reset via /reset")
    return {"ok": True, "wiped": True}
