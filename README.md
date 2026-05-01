# Goggins Agent

A personal AI drill instructor that watches your fitness habits and yells at you — over text and phone calls — when you slack off. Always running, always watching.

## The Concept

Every couple of hours, an autonomous agent wakes up, looks at your recent workouts, considers the time of day and your current "heat level" (a running tally of how much grief you've earned), and decides whether to stay quiet, send a brutal text, or place a phone call. If you reply to a text — with words *or* a meal photo — the agent reads it and fires back. The voice on phone calls is a custom-cloned drill instructor, not a robot reading text.

## Integrations

This project ties together seven moving parts. Each plays one role:

- **Anthropic (Claude Haiku 4.5)** — The brain. Runs as an autonomous agent loop with access to tools for reading workouts, checking state, sending texts, and placing calls. Vision-capable, so it can roast meal photos sent over Telegram.

- **Strava** — Source of truth for workouts. The agent pulls your recent activities (runs, lifts, rides) and judges them against a workout regime hardcoded in its system prompt.

- **Telegram** — Two-way messaging. Outbound texts go out through a bot; inbound replies and photos hit a webhook that wakes the agent. Photos are downloaded and passed straight to Claude as image input.

- **Twilio (Voice)** — Outbound phone calls only. When the agent decides to call, Twilio dials your phone and plays a generated audio clip hosted by this service.

- **ElevenLabs** — Voice synthesis. Converts the agent's text rant into a custom-cloned drill instructor voice for phone calls. A small library of pre-generated rants is also cached for filming, so calls can fire instantly without waiting on synthesis.

- **APScheduler** — In-process scheduler. Fires the agent on a recurring tick (with extra ticks at strategic times like early-morning weekdays) inside the same Python process as the web server.

- **Railway** — Deployment target. Runs the service continuously, handles inbound webhooks from Telegram, and serves the audio files Twilio plays during calls.

## How It Works

**Scheduled agent ticks.** On a recurring interval, the scheduler fires. The agent receives the current state (heat level, last action time, recent conversation), chooses tools to call — pull Strava, read state — and then either sends a text, places a call, or skips. One send-action per tick, hard stop. Crushing workouts cools the heat down and the agent backs off. Ducking workouts heats it up and it gets meaner.

**Inbound texts.** When you reply to a message — words, a photo of dinner, a weak excuse — Telegram forwards it to the service, the agent processes it (vision included for photos), and replies in character. Recent conversation history persists so threads feel continuous.

**Phone calls.** When the agent decides to call, it generates a short rant via ElevenLabs, hosts the audio publicly, and tells Twilio to dial your phone and play it. For filming, pre-generated rants can fire instantly without synthesis delay.

**Manual triggers.** A trigger endpoint lets you fire the agent on demand — useful when you want a text or call to happen on camera without waiting for the next scheduled tick.

## Running State

The agent keeps a small running log: recent conversation, last time it bothered you, and a heat score from 0 to 10 reflecting how much grief you've earned. The score nudges the agent's tone — calm at 0, unhinged at 10. Heat decays daily and climbs when you skip workouts.
