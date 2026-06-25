 🤖 HandleAI (Moksh)

[![Platform: Windows](https://img.shields.io/badge/platform-Windows-blue.svg)](https://www.microsoft.com/windows)
[![Language: Python](https://img.shields.io/badge/language-Python-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![License: Private](https://img.shields.io/badge/license-Private-red.svg)](LICENSE)

HandleAI is a local, private desktop assistant tailored for your PC. It processes everything directly on your machine—ensuring zero data leakage—and acts as an efficient bridge to control your system, process workspace files, manage notes, and draft contextual responses.

---

## ✨ Features

* **🖥️ App Control & Integration:** Quickly launch or close system utilities and applications (`Firefox`, `Chrome`, `Edge`, `Notepad`, `Calculator`, `Spotify`, `VS Code`, Windows Settings, Task Manager, and Terminal environments).
* **📁 Local Workspace Intelligence:** Fuzzy search, summarize, and explain native codebases (e.g., listing classes/functions in `.py` files) and documents directly from your local workspace.
* **📬 Email Summarization & Drafting:** Paste custom raw email headers/text to get quick, intelligent summaries and contextual response templates tailored to meeting requests or project milestones.
* **🗃️ Local Persistence (Memory):** Save, persist, and recall text-based reminders or notes locally without relying on external cloud storage.
* **🎙️ Optional Voice & UI Interface:** Includes a built-in interactive Tkinter Desktop UI alongside headless CLI support, with optional voice recognition capabilities.

---

## 🛠️ Architecture Overview

The system operates strictly inside a localized perimeter. It queries system variables, manages localized state buffers, and binds desktop hooks securely.



Getting Started

### Prerequisites

* **Operating System:** Windows (recommended for native `taskkill` and shortcut generation hooks; core functionality is cross-platform).
* **Python Version:** Python 3.8 or higher.

To enable **Voice Input/Output** workflows, ensure the following native packages are active on your system:
```bash
pip install keyboard pyttsx3 speech_recognition
