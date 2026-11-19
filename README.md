# Ray: your desktop voice assistant

Ray is a voice-first assistant for your Windows PC with a futuristic, Siri-style interface.
Say **"Hey Ray"** and it chimes, listens and answers out loud, like Alexa. Then it actually does
what you asked: opens apps, plays YouTube, changes settings, and with **agent mode** (Claude)
it can drive your browser like Comet: book things, fill in job applications, research with
live web search like Perplexity, and write code or hand it to Claude Code.

## Quick start

```bash
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then double-click **`launch_ray.cmd`** (or run `.\.venv\Scripts\python.exe pew.py`).

The UI works without any packages. `requirements.txt` adds the microphone ("Hey Ray") and
spoken replies. If `pyaudio` fails to install, try `pip install pipwin && pipwin install pyaudio`,
or use Python 3.12, which has prebuilt wheels.

### Agent mode (Claude)

Agent mode needs a Claude API key from [console.anthropic.com](https://console.anthropic.com).
Each agent task costs a few cents of API usage. Set the key once, then open a new terminal:

```bash
setx ANTHROPIC_API_KEY "sk-ant-..."
```

The top-left of the window shows **Claude agent ready** when it's on. Without a key, Ray uses
Ollama for questions instead (below), and everything else still works.

The first time Ray uses the browser it opens its own Chrome (or Edge) window. Sign in to the
sites you want it to use (LinkedIn, Gmail, booking sites); it remembers those logins.

For offline questions and conversation, install [Ollama](https://ollama.com) and pull a model:

```bash
ollama pull qwen3:8b
```

Pick a different model any time from the menu under the RAY title (`qwen2.5:3b` replies faster).

## Talking to Ray

| Say | What happens |
| --- | --- |
| "Hey Ray" ... *chime* ... "open Spotify" | Opens any installed app, or sites like YouTube, Gmail, Netflix |
| "Hey Ray, play lofi hip hop" | Finds it on YouTube and plays the top video |
| "Search YouTube for pasta recipes" | Shows the top results as cards and asks "Want me to play it?" |
| "Play that video" / "Play the second one" / "Yes" | Plays a result from the last search |
| "Next video" / "Pause" / "Resume" | Controls playback |
| "Volume up" / "Volume down" / "Mute" | Controls system volume |
| "Close Chrome" | Closes an app |
| "Search for weather in Tokyo" | Google search |
| "Open Downloads" | Opens a folder |
| "Remember my locker code is 4312" / "What do you remember?" | Local notes (`~/.ray/notes.txt`) |
| "What time is it?" / "Lock my PC" | Time, date, lock screen |
| "Open Notepad and then play some jazz" | Several commands at once |
| "Open Bluetooth settings" / "Close settings" | Any Windows Settings page |
| "Turn on dark mode" / "Brightness 40" / "Take a screenshot" | System controls |
| "Restart my PC" | Asks "Are you sure?" first |

### Agent mode examples

| Say | What happens |
| --- | --- |
| "What's the weather in Mumbai this weekend?" | Live web search, spoken answer |
| "Find Python developer jobs in Pune on LinkedIn and apply to the best one" | Opens LinkedIn in Ray's browser, fills the form, **asks before submitting** |
| "Book a table for two at an Italian place near me tonight" | Searches, picks options, **asks before booking** |
| "Write a Python script that renames my photos by date" | Writes it to `~/RayProjects` and opens it in VS Code |
| "Ask Claude Code to build me a to-do app" | Opens Claude Code in a terminal with the task |
| "Find out why my PC is slow" | Runs PowerShell commands, **each one approved by you** |

Ray always asks before spending money, booking, submitting, sending messages or deleting
anything, and you sign in, solve captchas and enter card details yourself. Press **Esc** to stop
the agent at any time.

You can also type in the box at the bottom, click the mic (or press **Ctrl+Space**) to talk without
the wake word, click a video card to play it, and press **Esc** to stop Ray talking.
Click **HEY RAY: ON** to turn the always-on wake word off, and **VOICE REPLIES** to mute spoken answers.

## Settings (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `OLLAMA_MODEL` | `qwen3:8b` | Model Ray starts with |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Where Ollama runs |
| `RAY_WAKE_WORD` | `1` | `0` starts with the wake word off |
| `RAY_STT` | `auto` | `auto` uses Whisper if installed, else Google; or force `whisper` / `google` |
| `RAY_WHISPER_MODEL` | `small.en` | `base.en` is faster on slow PCs, `medium.en` is more accurate |
| `ANTHROPIC_API_KEY` | | Turns on agent mode |
| `RAY_CLAUDE_MODEL` | `claude-opus-5-5` | Claude model for agent mode |
| `RAY_EFFORT` | `medium` | `low` is faster and cheaper, `high` is more careful |
| `RAY_BROWSER_PATH` | | Use another Chromium browser (e.g. Brave) for agent mode |
| `RAY_VOICE` | `zira` | Part of the name of the Windows voice Ray speaks with |

Speech recognition uses Whisper, which runs on your PC and handles accents and app names well.
The first time, it downloads its model (about 500 MB). If Whisper isn't installed, Ray uses
Google's free web recognizer instead. The wake word only counts at the start of a sentence, so
talking about Ray in the room won't trigger it.

## Start with Windows

```bash
.\.venv\Scripts\python.exe pew.py --install-startup
```

## Command line and tests

```bash
python pew.py play lofi music
python -m pytest tests -q
```

## Project layout

```
pew.py            entry point
ray/commands.py   understands what you say and decides what to do
ray/system.py     opens/closes apps, websites, media and volume keys
ray/youtube.py    live YouTube search (no API key)
ray/agent.py      agent mode: Claude with PC, browser, web search and coding tools
ray/browser.py    the browser window the agent drives (keeps your logins)
ray/brain.py      local Ollama conversation (offline fallback)
ray/voice.py      "Hey Ray" wake word, chime, text-to-speech
ray/ui.py         the animated interface
```
