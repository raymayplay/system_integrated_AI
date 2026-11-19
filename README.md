# Ray: your desktop voice assistant

Ray is a voice-first assistant for your Windows PC with a futuristic, Siri-style interface.
Say **"Hey Ray"** and it chimes, listens and answers out loud, like Alexa. Then it actually does
what you asked: opens apps, searches and plays YouTube videos, controls your music and volume,
and answers questions using a local AI model.

## Quick start

```bash
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then double-click **`launch_ray.cmd`** (or run `.\.venv\Scripts\python.exe pew.py`).

The UI works without any packages. `requirements.txt` adds the microphone ("Hey Ray") and
spoken replies. If `pyaudio` fails to install, try `pip install pipwin && pipwin install pyaudio`,
or use Python 3.12, which has prebuilt wheels.

For questions and conversation, install [Ollama](https://ollama.com) and pull a model:

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
| Anything else | Answered by your local Ollama model, which can also trigger actions |

You can also type in the box at the bottom, click the mic (or press **Ctrl+Space**) to talk without
the wake word, click a video card to play it, and press **Esc** to stop Ray talking.
Click **HEY RAY: ON** to turn the always-on wake word off, and **VOICE REPLIES** to mute spoken answers.

## Settings (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `OLLAMA_MODEL` | `qwen3:8b` | Model Ray starts with |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Where Ollama runs |
| `RAY_WAKE_WORD` | `1` | `0` starts with the wake word off |
| `RAY_OFFLINE_SPEECH` | `0` | `1` uses offline PocketSphinx instead of Google speech recognition |
| `RAY_VOICE` | `zira` | Part of the name of the Windows voice Ray speaks with |

Speech recognition uses Google's free web recognizer by default because it is far more accurate.
Audio is only sent after the microphone picks up speech. Set `RAY_OFFLINE_SPEECH=1` (and install
`PocketSphinx`) to keep everything offline. Ollama always runs locally.

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
ray/brain.py      local Ollama conversation
ray/voice.py      "Hey Ray" wake word, chime, text-to-speech
ray/ui.py         the animated interface
```
