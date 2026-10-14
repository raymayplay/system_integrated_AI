 🤖 HandleAI (Moksh)

[![Platform: Windows](https://img.shields.io/badge/platform-Windows-blue.svg)](https://www.microsoft.com/windows)
[![Language: Python](https://img.shields.io/badge/language-Python-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![License: Private](https://img.shields.io/badge/license-Private-red.svg)](LICENSE)

HandleAI is an original local, private desktop assistant tailored for your PC. It processes everything directly on your machine—ensuring zero data leakage—and acts as an efficient bridge to control your system, process workspace files, manage notes, and draft contextual responses.

This project is intentionally built from original code and local-first patterns. It does not copy or redistribute copyrighted GitHub source code or other open-source projects without permission.

---

## ✨ Features

* **🖥️ App Control & Integration:** Quickly launch or close system utilities and applications (`Firefox`, `Chrome`, `Edge`, `Notepad`, `Calculator`, `Spotify`, `VS Code`, Windows Settings, Task Manager, and Terminal environments).
* **📁 Local Workspace Intelligence:** Fuzzy search, summarize, and explain native codebases (e.g., listing classes/functions in `.py` files) and documents directly from your local workspace.
* **📬 Email Summarization & Drafting:** Paste custom raw email headers/text to get quick, intelligent summaries and contextual response templates tailored to meeting requests or project milestones.
* **🗃️ Local Persistence (Memory):** Save, persist, and recall text-based reminders or notes locally without relying on external cloud storage.
* **🎙️ Offline Voice & UI Interface:** Includes an interactive desktop UI and one-shot offline English voice commands. The assistant is named Ray; voice is opt-in and does not listen continuously at startup.
* **🧠 Local Ollama Models:** Connects to Ollama on this PC, lists every model already installed locally, and lets you choose which one Ray uses.

---

## 🛠️ Architecture Overview

The system operates strictly inside a localized perimeter. It queries system variables, manages localized state buffers, and binds desktop hooks securely.



Getting Started

### Prerequisites

* **Operating System:** Windows (recommended for native `taskkill` and shortcut generation hooks; core functionality is cross-platform).
* **Python Version:** Python 3.8 or higher.

Ray's desktop UI and Ollama chat do not require extra Python packages. Create the virtual environment and install the (currently standard-library-only) base requirements with:
```bash
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements_ray.txt
```

Launch Ray with:
```bash
.\.venv\Scripts\python.exe .\pew.py
```

Voice input/output is optional and has native microphone dependencies. Install these separately:
```bash
.\.venv\Scripts\python.exe -m pip install -r requirements_voice.txt
```
On Windows with Python 3.14, PyAudio and PocketSphinx may not have compatible prebuilt wheels; pip then needs Microsoft C++ Build Tools and CMake. If you do not need voice commands, skip this optional install—Ray's Ollama chat works without it.

### Local AI with Ollama

Ollama and local model files are already present on this PC: `qwen2.5:3b` and `qwen3:8b`. Ray offers both in the model selector and defaults to `qwen3:8b`; set `OLLAMA_MODEL` to change the initial selection. AI requests use `http://127.0.0.1:11434` by default. `/ai <prompt>` always sends directly to the selected local model. The older advanced-prompt path can be explicitly redirected by setting `LOCAL_AI_USE_REMOTE=1`; leave it unset for local-only operation.

To try Ray:

```bash
ollama list
ollama run qwen3:8b
```

Then open `launch_ray.cmd`, select a model, and enter `/ai Explain how a local language model works`. Choose `qwen2.5:3b` in the model selector to use the lighter model. If the UI says Ollama is unavailable, start Ollama from the Start menu and click **Refresh Model List**. If `ollama list` does not show a model, download it with `ollama pull qwen3:8b` or `ollama pull qwen2.5:3b`. Models run on this PC and are not downloaded by Ray. Set `OLLAMA_BASE_URL` only if your local Ollama uses a different address.

Run the focused tests from the project directory with:

```bash
python -m pytest test_ollama_integration.py test_ai_language_features.py -q
```

Voice commands are optional; install the packages in `requirements_voice.txt` if voice dependencies are missing, then click **VOICE COMMAND** and say “Hey Ray” followed by your command.

### Start Ray with Windows

Run `python pew.py --install-startup` to add Ray to the current Windows user's Startup folder. It opens the desktop UI at sign-in and does not enable continuous microphone listening. To remove auto-start, delete **Ray Assistant** from the Startup folder.
