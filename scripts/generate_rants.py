"""
Pre-generate SMS variants and mp3 call rants for filming.
Files land in ./rants/.

Run:
    uv run python scripts/generate_rants.py            # default: 5 of each
    uv run python scripts/generate_rants.py --count 1  # quick test: 1 of each
"""
import argparse
import os
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from main import SYSTEM_PROMPT  # reuse the drill-instructor persona

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
ELEVENLABS_VOICE_ID = os.environ["ELEVENLABS_VOICE_ID"]

RANTS_DIR = Path("rants")
RANTS_DIR.mkdir(exist_ok=True)

anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

SCENARIOS = {
    "skipped": "The user skipped their workout entirely. No Strava activity for the day. They had no excuse.",
    "weak": "The user logged a workout, but it was pathetic — too short, too slow, half-assed. They went through the motions.",
}

def generate_text(scenario_desc: str, mode: str) -> str:
    length = "1-3 sentences (SMS length)" if mode == "sms" else "4-6 sentences (phone call length)"
    user = f"Scenario: {scenario_desc}\n\nWrite ONE {mode} rant of {length}. Output ONLY the message text — no preamble, no quotes, no labels."
    resp = anthropic_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()

def synth(text: str, out_path: Path) -> None:
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

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=5, help="Number of variants per scenario (default 5)")
    args = parser.parse_args()
    for scenario, desc in SCENARIOS.items():
        for i in range(1, args.count + 1):
            sms_text = generate_text(desc, "sms")
            sms_path = RANTS_DIR / f"sms_{scenario}_{i}.txt"
            sms_path.write_text(sms_text)
            print(f"[sms] {sms_path.name}: {sms_text}")

            call_text = generate_text(desc, "call")
            (RANTS_DIR / f"call_{scenario}_{i}.txt").write_text(call_text)
            call_mp3_path = RANTS_DIR / f"call_{scenario}_{i}.mp3"
            synth(call_text, call_mp3_path)
            print(f"[call] {call_mp3_path.name}: {call_text}")

    n = len(SCENARIOS) * args.count
    print(f"\nDone. {n} SMS + {n} call rants written to ./rants/")

if __name__ == "__main__":
    main()
