#!/usr/bin/env python3
"""Private desktop assistant for your PC.

This script runs fully on your own machine and can:
- open apps such as Firefox, Notepad, Calculator, or Terminal
- open websites and search the web
- play or launch media apps
- summarize and explain files in your workspace
- remember notes locally
- optionally use voice input/output when the required Python packages are available
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import webbrowser
from difflib import get_close_matches
from pathlib import Path
from typing import List, Optional
import tkinter as tk
from tkinter import messagebox, scrolledtext

try:
    import keyboard  # type: ignore
except Exception:
    keyboard = None

WORKSPACE_ROOT = Path(os.getenv("LOCAL_AI_WORKSPACE", os.getcwd())).resolve()


class LocalPrivateAssistant:
    def __init__(self, workspace_root: str | None = None):
        self.workspace_root = Path(workspace_root or WORKSPACE_ROOT).resolve()
        self.memory_path = self.workspace_root / ".local_ai_memory.txt"
        self.memory = self._load_memory()
        self.voice_enabled = False
        self._speech_engine = None
        self._recognizer = None

    def _load_memory(self) -> List[str]:
        if self.memory_path.exists():
            try:
                return [line.strip() for line in self.memory_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            except Exception:
                return []
        return []

    def _save_memory(self) -> None:
        self.memory_path.write_text("\n".join(self.memory) + "\n", encoding="utf-8")

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.lower()).strip()

    def _extract_keywords(self, text: str) -> List[str]:
        words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        stop_words = {
            "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "is", "are", "be", "my", "i", "you",
            "it", "this", "that", "with", "from", "can", "help", "please", "show", "give", "what", "how", "why",
            "when", "where", "do", "does", "did", "your", "me", "we", "our", "about", "into", "just", "like"
        }
        return [w for w in words if len(w) > 2 and w not in stop_words]

    def _find_relevant_file(self, query: str) -> Optional[Path]:
        query_words = set(self._extract_keywords(query))
        if not query_words:
            return None

        candidates: List[tuple[float, Path]] = []
        for path in self.workspace_root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in {".pyc", ".exe", ".dll", ".bin", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".mp3", ".zip"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            words = set(self._extract_keywords(text))
            overlap = len(query_words & words)
            if overlap > 0:
                score = overlap + (1 if any(word in path.name.lower() for word in query_words) else 0)
                candidates.append((score, path))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _resolve_path(self, file_path: str) -> Path:
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            path = (self.workspace_root / path).resolve()
        return path

    def _launch_with_startfile(self, target: str) -> bool:
        if hasattr(os, "startfile"):
            try:
                os.startfile(target)
                return True
            except OSError:
                return False
        return False

    def resolve_special_target(self, prompt: str) -> Optional[tuple[str, str]]:
        p = self._normalize(prompt)

        if any(token in p for token in ["gmail", "google mail", "mail"]):
            return ("website", "https://mail.google.com")
        if any(token in p for token in ["settings", "system settings", "windows settings", "settings app"]):
            return ("app", "ms-settings:")
        if any(token in p for token in ["control panel", "controlpanel"]):
            return ("app", "control.exe")
        if any(token in p for token in ["task manager", "taskmgr"]):
            return ("app", "taskmgr.exe")
        if any(token in p for token in ["my computer", "this pc", "file explorer"]):
            return ("app", "explorer.exe")
        if any(token in p for token in ["outlook", "mail app"]):
            return ("app", "outlook.exe")
        if any(token in p for token in ["calendar", "google calendar"]):
            return ("website", "https://calendar.google.com")
        if any(token in p for token in ["drive", "google drive"]):
            return ("website", "https://drive.google.com")

        home = Path.home()
        if "documents" in p:
            return ("folder", str(home / "Documents"))
        if any(token in p for token in ["downloads", "downloads folder"]):
            return ("folder", str(home / "Downloads"))
        if any(token in p for token in ["desktop", "desktop folder"]):
            return ("folder", str(home / "Desktop"))
        if any(token in p for token in ["pictures", "photos"]):
            return ("folder", str(home / "Pictures"))
        if any(token in p for token in ["music", "songs"]):
            return ("folder", str(home / "Music"))
        if any(token in p for token in ["videos", "movies"]):
            return ("folder", str(home / "Videos"))

        return None

    def open_special_target(self, prompt: str) -> str:
        target = self.resolve_special_target(prompt)
        if target is None:
            return "I don't have a special target for that request."

        kind, value = target
        if kind == "website":
            webbrowser.open(value)
            return f"Opened {value}."

        if kind == "folder":
            folder = Path(value).expanduser()
            if folder.exists():
                self._launch_with_startfile(str(folder))
                return f"Opened folder: {folder}"
            return f"Folder not found: {folder}"

        if kind == "app":
            if value.startswith("ms-settings:"):
                self._launch_with_startfile(value)
                return "Opened Windows Settings."
            if os.path.exists(value):
                self._launch_with_startfile(value)
                return f"Opened {value}."
            if shutil.which(value):
                subprocess.Popen([value])
                return f"Opened {value}."
            if self._launch_with_startfile(value):
                return f"Opened {value}."
            return f"I could not open {value}."

        return f"Opened {value}."

    def launch_app(self, app_name: str) -> str:
        a = app_name.strip().lower()
        app_map = {
            "firefox": ["firefox.exe", "C:\\Program Files\\Mozilla Firefox\\firefox.exe", "C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe"],
            "chrome": ["chrome.exe", "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"],
            "edge": ["msedge.exe", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"],
            "notepad": ["notepad.exe"],
            "calculator": ["calc.exe"],
            "terminal": ["wt.exe", "cmd.exe"],
            "cmd": ["cmd.exe"],
            "powershell": ["powershell.exe"],
            "explorer": ["explorer.exe"],
            "vscode": ["code.exe"],
            "spotify": ["spotify.exe"],
        }

        if a in app_map:
            for candidate in app_map[a]:
                if os.path.exists(candidate):
                    self._launch_with_startfile(candidate)
                    return f"Opened {app_name}."
                if shutil.which(candidate):
                    subprocess.Popen([candidate])
                    return f"Opened {app_name}."

            if a in {"firefox", "chrome", "edge", "notepad", "calculator", "terminal", "cmd", "powershell", "explorer", "vscode", "spotify"}:
                if self._launch_with_startfile(a):
                    return f"Opened {app_name}."
            return f"I could not find {app_name} on this PC."

        if self._launch_with_startfile(a):
            return f"Opened {app_name}."
        return f"I don't know how to open {app_name}."

    def build_search_url(self, query: str) -> str:
        q = query.strip()
        if not q:
            return "https://www.google.com"
        if q.lower() in {"youtube", "youtube.com", "www.youtube.com"}:
            return "https://www.youtube.com"
        if q.startswith("http://") or q.startswith("https://"):
            return q
        return f"https://www.google.com/search?q={q.replace(' ', '+')}"

    def open_website(self, site: str) -> str:
        if not site:
            return "Please provide a website or search term."
        target = site.strip()
        if target.lower() in {"youtube", "youtube.com", "www.youtube.com"}:
            target = "https://www.youtube.com"
        elif "." not in target and " " not in target:
            target = f"https://www.{target}.com"
        elif "http" not in target:
            target = f"https://{target}"
        self.launch_app("firefox")
        webbrowser.open(target)
        return f"Opened website: {target}"

    def search_web(self, query: str) -> str:
        url = self.build_search_url(query)
        self.launch_app("firefox")
        webbrowser.open(url)
        return f"Opened web search for: {query}"

    def remember(self, note: str) -> str:
        note = note.strip()
        if not note:
            return "Please provide something to remember."
        self.memory.append(note)
        self._save_memory()
        return f"Saved locally: {note}"

    def show_memory(self) -> str:
        if self.memory:
            return "Local memory:\n- " + "\n- ".join(self.memory)
        return "No saved notes yet."

    def parse_raw_email_message(self, raw_message: bytes) -> dict[str, str]:
        text = raw_message.decode("utf-8", errors="ignore")
        headers = {}
        body_lines = []
        in_body = False
        for line in text.splitlines():
            if not in_body and line.startswith("From:"):
                headers["from"] = line.split(":", 1)[1].strip()
            elif not in_body and line.startswith("Subject:"):
                headers["subject"] = line.split(":", 1)[1].strip()
            elif not in_body and line.strip() == "":
                in_body = True
            elif in_body:
                body_lines.append(line)
        headers["body"] = "\n".join(body_lines).strip()
        return headers

    def summarize_email_text(self, email_text: str) -> str:
        text = email_text.strip()
        if not text:
            return "No email content to summarize."
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        subject = next((line for line in lines if line.lower().startswith("subject:")), "Email")
        summary = f"{subject}: "
        if len(text) > 220:
            summary += text[:220].replace("\n", " ") + "..."
        else:
            summary += text.replace("\n", " ")
        return summary

    def get_gmail_credentials(self) -> Optional[dict[str, str]]:
        cred_path = self.workspace_root / "gmail_credentials.json"
        if not cred_path.exists():
            return None
        try:
            data = json.loads(cred_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("email") and data.get("password"):
                return {"email": str(data["email"]), "password": str(data["password"])}
        except Exception:
            return None
        return None

    def build_gmail_inbox_summary(self) -> str:
        credentials = self.get_gmail_credentials()
        if credentials is None:
            return "No Gmail credentials found. Create gmail_credentials.json with email and password to enable inbox reading."
        return (
            f"Gmail access is configured for {credentials['email']}. "
            "This local app can summarize incoming mail once the mailbox is fetched through your browser or a mail client."
        )

    def build_system_status(self) -> str:
        return (
            f"Platform: {platform.platform()}\n"
            f"System: {platform.system()} {platform.release()}\n"
            f"CPU: {platform.processor() or 'unknown'}\n"
            f"Python: {platform.python_version()}"
        )

    def list_directory_contents(self, directory: str) -> List[str]:
        path = Path(directory).expanduser()
        if not path.exists():
            return []
        if not path.is_dir():
            return [path.name]
        return sorted([child.name for child in path.iterdir()])

    def close_app(self, app_name: str) -> str:
        name = app_name.strip().lower()
        if os.name != "nt":
            return "This feature is currently available on Windows."
        try:
            subprocess.run(["taskkill", "/F", "/IM", f"{name}.exe"], check=False, capture_output=True, text=True)
            return f"Closed {app_name}."
        except Exception as exc:
            return f"Could not close {app_name}: {exc}"

    def build_reply_draft(self, email_text: str) -> str:
        text = email_text.strip()
        if not text:
            return "Hi there,\n\nThanks for your message. I will follow up shortly.\n\nBest,\nHandleAI"

        sender = "there"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in reversed(lines):
            lowered = line.lower()
            if lowered.startswith("subject:") or lowered.startswith("hi ") or lowered.startswith("hello"):
                continue
            if lowered.startswith("thanks") or lowered.startswith("best") or lowered.startswith("regards"):
                continue
            sender = line
            break

        sender_name = sender.replace(",", "").strip()
        if not sender_name or sender_name.lower() in {"thanks", "best", "regards"}:
            sender_name = "there"

        purpose = ""
        lowered_text = text.lower()
        if "meeting" in lowered_text:
            purpose = " I can help with the meeting details."
        elif "project" in lowered_text:
            purpose = " I can help with the project update."
        elif "review" in lowered_text:
            purpose = " I can help with the review."

        return (
            f"Hi {sender_name},\n\nThanks for your message. I have reviewed it and will follow up shortly.{purpose}\n\nBest,\nHandleAI"
        )

    def install_startup(self) -> str:
        startup_dir = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")
        os.makedirs(startup_dir, exist_ok=True)

        launcher_path = self.workspace_root / "start_assistant.cmd"
        launcher_path.write_text(
            "@echo off\n"
            "setlocal\n"
            f"cd /d \"{self.workspace_root}\"\n"
            "where py >nul 2>nul\n"
            "if %ERRORLEVEL% EQU 0 (\n"
            f"  py -3 \"{self.workspace_root / 'pew.py'}\" --auto\n"
            ") else (\n"
            f"  python \"{self.workspace_root / 'pew.py'}\" --auto\n"
            ")\n",
            encoding="utf-8",
        )

        shortcut_path = Path(startup_dir) / "pew_assistant.lnk"
        ps_script = (
            "$WshShell = New-Object -ComObject WScript.Shell; "
            f"$Shortcut = $WshShell.CreateShortcut('{shortcut_path}'); "
            f"$Shortcut.TargetPath = '{launcher_path}'; "
            f"$Shortcut.WorkingDirectory = '{self.workspace_root}'; "
            "$Shortcut.WindowStyle = 7; "
            "$Shortcut.Save()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True, capture_output=True, text=True)
        tray_launcher_path = self.workspace_root / "tray_launcher.py"
        if tray_launcher_path.exists():
            shortcut_path2 = Path(startup_dir) / "handleai_tray.lnk"
            ps_script2 = (
                "$WshShell = New-Object -ComObject WScript.Shell; "
                f"$Shortcut = $WshShell.CreateShortcut('{shortcut_path2}'); "
                f"$Shortcut.TargetPath = '{sys.executable}'; "
                f"$Shortcut.Arguments = '\"{tray_launcher_path}\"'; "
                f"$Shortcut.WorkingDirectory = '{self.workspace_root}'; "
                "$Shortcut.WindowStyle = 7; "
                "$Shortcut.Save()"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_script2], check=True, capture_output=True, text=True)

        return f"Installed startup shortcut at {shortcut_path}"

    def summarize_file(self, file_path: str) -> str:
        path = self._resolve_path(file_path)
        if not path.exists():
            raise ValueError(f"File not found: {path}")
        if path.is_dir():
            raise ValueError(f"Path is a directory, not a file: {path}")

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="ignore")

        lines = [line.rstrip() for line in content.splitlines() if line.strip()]
        if not lines:
            return "The file is empty."

        if path.suffix.lower() == ".py":
            functions = re.findall(r"def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", content)
            classes = re.findall(r"class\s+([A-Za-z_][A-Za-z0-9_]*)", content)
            summary_parts = [f"Python file: {path.name}"]
            if functions:
                summary_parts.append("Functions: " + ", ".join(functions[:8]))
            if classes:
                summary_parts.append("Classes: " + ", ".join(classes[:8]))
            summary_parts.append("Preview: " + " ".join(lines[:6]))
            return "\n".join(summary_parts)

        heading = next((line for line in lines if line.startswith("#") or len(line) < 80), lines[0])
        return f"File: {path.name}\nSummary: {heading}\nPreview: {' '.join(lines[:6])}"

    def explain_file(self, file_path: str) -> str:
        path = self._resolve_path(file_path)
        if not path.exists():
            raise ValueError(f"File not found: {path}")
        if path.is_dir():
            raise ValueError(f"Path is a directory, not a file: {path}")

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="ignore")

        lines = [line.rstrip() for line in content.splitlines() if line.strip()]
        if not lines:
            return "The file is empty."

        if path.suffix.lower() == ".py":
            imports = re.findall(r"^import\s+([A-Za-z0-9_.]+)", content, flags=re.MULTILINE)
            from_imports = re.findall(r"^from\s+([A-Za-z0-9_.]+)\s+import", content, flags=re.MULTILINE)
            explanation = [f"This appears to be a Python file named {path.name}."]
            if imports:
                explanation.append("Imports: " + ", ".join(imports[:6]))
            if from_imports:
                explanation.append("From imports: " + ", ".join(from_imports[:6]))
            explanation.append("It likely contains executable logic and helper functions.")
            return "\n".join(explanation)

        return (
            f"This file appears to be a text or data file named {path.name}. "
            "Its contents can be read directly, and I can help summarize the important sections."
        )

    def _setup_voice(self) -> bool:
        try:
            import pyttsx3  # type: ignore
            import speech_recognition as sr  # type: ignore
        except ImportError:
            return False

        self._speech_engine = pyttsx3.init()
        self._recognizer = sr.Recognizer()
        self.voice_enabled = True
        return True

    def speak(self, text: str) -> None:
        print(f"Assistant> {text}")
        if self.voice_enabled and self._speech_engine is not None:
            try:
                self._speech_engine.say(text)
                self._speech_engine.runAndWait()
            except Exception:
                pass

    def listen_once(self) -> Optional[str]:
        if not self.voice_enabled or self._recognizer is None:
            return None

        try:
            import speech_recognition as sr  # type: ignore
        except ImportError:
            return None

        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self._recognizer.listen(source, timeout=6, phrase_time_limit=6)
            return self._recognizer.recognize_sphinx(audio)
        except Exception:
            return None

    def _normalize_tokens(self, text: str) -> List[str]:
        return [token for token in re.split(r"[^a-z0-9]+", self._normalize(text)) if token]

    def _fuzzy_matches(self, text: str, targets: List[str]) -> bool:
        tokens = set(self._normalize_tokens(text))
        return any(token in tokens for token in targets)

    def _looks_like_app_request(self, text: str) -> bool:
        normalized = self._normalize(text)
        if not normalized:
            return False
        app_terms = ["firefox", "chrome", "edge", "notepad", "calculator", "settings", "gmail", "youtube", "spotify", "vscode", "terminal", "cmd", "powershell", "explorer"]
        tokens = self._normalize_tokens(normalized)
        for token in tokens:
            if token in app_terms:
                return True
            if get_close_matches(token, app_terms, n=1, cutoff=0.6):
                return True
        if any(word in normalized for word in ["open ", "launch ", "start ", "run ", "goto ", "go to "]):
            return True
        return False

    def _normalize_app_name(self, prompt: str) -> str:
        tokens = self._normalize_tokens(prompt)
        aliases = {
            "opne": "open",
            "opn": "open",
            "oprn": "open",
            "launh": "launch",
            "launchh": "launch",
            "startt": "start",
            "goto": "go to",
            "goot": "go to",
            "firefoz": "firefox",
            "firefoxz": "firefox",
            "firefow": "firefox",
            "notepadd": "notepad",
            "caluclator": "calculator",
            "calc": "calculator",
            "setings": "settings",
            "gmails": "gmail",
            "youtub": "youtube",
            "yt": "youtube",
            "poweshell": "powershell",
            "terminall": "terminal",
            "explorrer": "explorer",
        }
        app_terms = ["firefox", "chrome", "edge", "notepad", "calculator", "settings", "gmail", "youtube", "spotify", "vscode", "terminal", "cmd", "powershell", "explorer"]
        for token in tokens:
            normalized_token = aliases.get(token, token)
            if normalized_token in app_terms:
                return normalized_token
            match = get_close_matches(normalized_token, app_terms, n=1, cutoff=0.6)
            if match:
                return match[0]
        return ""

    def handle_command(self, prompt: str) -> str:
        if not prompt.strip():
            return "Please tell me what to do."

        bridge_script = self.workspace_root / "desktop_ai_bridge.py"
        if bridge_script.exists() and self._fuzzy_matches(prompt, ["open", "launch", "start", "run", "search", "youtube", "gmail", "settings", "firefox", "chrome", "edge", "notepad"]):
            try:
                result = subprocess.run(
                    [sys.executable, str(bridge_script), prompt],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass

        p = self._normalize(prompt)

        if any(token in p for token in ["hello", "hi", "hey"]):
            return "Hello, Moksh. I am HandleAI, your private assistant. I can open apps, search the web, summarize files, and remember notes with a little extra charm."

        if any(token in p for token in ["what can you do", "help"]):
            return "I can open apps like Firefox and Notepad, open websites, play media, summarize files, explain code, and remember notes locally — fast, witty, and ready."

        if any(token in p for token in ["joke", "funny", "humor"]):
            return "Of course. Why did the robot bring a ladder? To reach new heights, obviously."

        if any(re.search(rf"\b{re.escape(token)}\b", p) for token in ["remember", "note", "save"]):
            note = prompt.replace("remember", "", 1).replace("note", "", 1).replace("save", "", 1).strip()
            if note and note.lower() in {"open notepad", "open firefox", "open calculator", "play music", "play video"}:
                return self.handle_command(note)
            return self.remember(note)

        if any(re.search(rf"\b{re.escape(token)}\b", p) for token in ["memory", "notes"]):
            return self.show_memory()

        if any(re.search(rf"\b{re.escape(token)}\b", p) for token in ["time", "date"]):
            return f"The current time is {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}."

        if any(token in p for token in ["system info", "system status", "hardware", "specs"]):
            return self.build_system_status()

        if self._looks_like_app_request(prompt):
            app_name = self._normalize_app_name(prompt)
            if app_name and self.resolve_special_target(app_name) is not None:
                return self.open_special_target(app_name)
            if any(token in app_name for token in ["firefox", "chrome", "edge", "notepad", "calculator", "settings", "gmail", "youtube", "spotify", "vscode", "terminal", "cmd", "powershell", "explorer"]):
                return self.launch_app(app_name)

        if self._fuzzy_matches(prompt, ["search", "find", "look", "what", "who", "when", "where", "why", "how"]) and not self._fuzzy_matches(prompt, ["system", "status", "specs", "hardware"]):
            if any(token in p for token in ["youtube", "gmail", "google", "browser", "web"]):
                return self.search_web(prompt)
            return self.search_web(prompt)

        if any(token in p for token in ["list folder", "show folder", "list directory", "open folder"]):
            target = prompt.replace("list folder", "", 1).replace("show folder", "", 1).replace("list directory", "", 1).replace("open folder", "", 1).strip()
            if not target:
                target = str(self.workspace_root)
            return "Contents:\n- " + "\n- ".join(self.list_directory_contents(target))

        if any(token in p for token in ["close", "kill"]):
            target = prompt.replace("close", "", 1).replace("kill", "", 1).strip()
            if target:
                return self.close_app(target)

        if self.resolve_special_target(prompt) is not None:
            return self.open_special_target(prompt)

        if p.startswith("open ") or " open " in p:
            app_name = prompt.replace("open", "", 1).strip()
            if app_name:
                return self.launch_app(app_name)

        if p.startswith("launch ") or " launch " in p:
            app_name = prompt.replace("launch", "", 1).strip()
            if app_name:
                return self.launch_app(app_name)

        if p.startswith("go to ") or p.startswith("open website ") or p.startswith("visit "):
            target = prompt.replace("go to", "", 1).replace("open website", "", 1).replace("visit", "", 1).strip()
            return self.open_website(target)

        if p.startswith("search ") or "search for " in p:
            query = prompt.replace("search for", "", 1).replace("search", "", 1).strip()
            return self.search_web(query)

        if any(token in p for token in ["youtube", "you tube"]):
            self.launch_app("firefox")
            webbrowser.open("https://www.youtube.com")
            return "Opened YouTube in Firefox."

        if any(token in p for token in ["play", "music", "song", "video"]):
            if "spotify" in p:
                return self.launch_app("spotify")
            return self.launch_app("firefox")

        if any(token in p for token in ["summarize", "explain"]):
            parts = prompt.split(maxsplit=1)
            if len(parts) > 1:
                target = parts[1].strip()
                if parts[0].lower() == "summarize":
                    return self.summarize_file(target)
                if parts[0].lower() == "explain":
                    return self.explain_file(target)

        relevant_file = self._find_relevant_file(prompt)
        if relevant_file is not None:
            return (
                f"I found a likely relevant file: {relevant_file.relative_to(self.workspace_root)}. "
                "Ask me to summarize or explain it."
            )

        return (
            "I can help with your PC, open apps, browse the web, summarize files, and remember notes. "
            "For general knowledge or broader questions, I will open a web search so you can get the answer quickly."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Private desktop assistant")
    parser.add_argument("--prompt", help="Run a single prompt and exit")
    parser.add_argument("--file", help="Read a file and summarize or explain it")
    parser.add_argument("--mode", choices=["chat", "summarize", "explain"], default="chat", help="What to do with the provided file")
    parser.add_argument("--voice", action="store_true", help="Try voice input and speech output")
    parser.add_argument("--auto", action="store_true", help="Start the continuous assistant loop")
    parser.add_argument("--install-startup", action="store_true", help="Install a Windows startup shortcut")
    return parser


def print_help() -> None:
    print("Commands:")
    print("  !help                Show this help")
    print("  !memory              Show saved notes")
    print("  !summarize <file>    Summarize a file in the workspace")
    print("  !explain <file>      Explain a file in the workspace")
    print("  !exit                Quit")


class AssistantDesktopUI:
    def __init__(self, assistant: LocalPrivateAssistant):
        self.assistant = assistant
        self.root = tk.Tk()
        self.root.title("HandleAI Moksh")
        self.root.geometry("800x600")
        self.root.configure(bg="#111827")

        tk.Label(self.root, text="HandleAI Moksh", fg="#f9fafb", bg="#111827", font=("Segoe UI", 20, "bold")).pack(pady=(16, 8))
        tk.Label(self.root, text="Local desktop assistant for Gmail, apps, files, and notes", fg="#cbd5e1", bg="#111827").pack()

        frame = tk.Frame(self.root, bg="#1f2937")
        frame.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(frame, text="Paste email content", fg="#f9fafb", bg="#1f2937", anchor="w").pack(fill="x")
        self.email_input = scrolledtext.ScrolledText(frame, height=10, wrap="word", bg="#111827", fg="#f9fafb", insertbackground="white")
        self.email_input.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        button_frame = tk.Frame(frame, bg="#1f2937")
        button_frame.pack(fill="x", pady=(0, 8))
        tk.Button(button_frame, text="Summarize", command=self.handle_summarize, bg="#2563eb", fg="white", width=16).pack(side="left", padx=4)
        tk.Button(button_frame, text="Draft reply", command=self.handle_reply, bg="#7c3aed", fg="white", width=16).pack(side="left", padx=4)
        tk.Button(button_frame, text="Open Gmail", command=self.handle_gmail, bg="#059669", fg="white", width=16).pack(side="left", padx=4)
        tk.Button(button_frame, text="Inbox summary", command=self.handle_inbox_summary, bg="#dc2626", fg="white", width=16).pack(side="left", padx=4)
        tk.Button(button_frame, text="System info", command=self.handle_system_status, bg="#0f766e", fg="white", width=16).pack(side="left", padx=4)

        tk.Label(frame, text="Or type a desktop command", fg="#f9fafb", bg="#1f2937", anchor="w").pack(fill="x", pady=(8, 4))
        self.command_input = tk.Entry(frame, bg="#111827", fg="#f9fafb", insertbackground="white")
        self.command_input.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(frame, text="Run command", command=self.handle_command_run, bg="#f59e0b", fg="black", width=16).pack(anchor="w", padx=8, pady=(0, 8))

        self.output = scrolledtext.ScrolledText(frame, height=12, wrap="word", bg="#0f172a", fg="#e2e8f0", insertbackground="white")
        self.output.pack(fill="both", expand=True, padx=8, pady=(4, 0))
        self.output.insert(tk.END, "Ready. Paste email text and click an action.\n")

    def handle_summarize(self) -> None:
        email_text = self.email_input.get("1.0", tk.END).strip()
        if not email_text:
            messagebox.showinfo("HandleAI", "Paste email content first.")
            return
        result = self.assistant.summarize_email_text(email_text)
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, result)

    def handle_reply(self) -> None:
        email_text = self.email_input.get("1.0", tk.END).strip()
        if not email_text:
            messagebox.showinfo("HandleAI", "Paste email content first.")
            return
        result = self.assistant.build_reply_draft(email_text)
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, result)

    def handle_gmail(self) -> None:
        self.assistant.open_special_target("open gmail")
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, "Opened Gmail in your browser.\n")

    def handle_inbox_summary(self) -> None:
        result = self.assistant.build_gmail_inbox_summary()
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, result)

    def handle_system_status(self) -> None:
        result = self.assistant.build_system_status()
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, result)

    def handle_command_run(self) -> None:
        prompt = self.command_input.get().strip()
        if not prompt:
            messagebox.showinfo("HandleAI", "Type a command first.")
            return
        result = self.assistant.handle_command(prompt)
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, result)

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    assistant = LocalPrivateAssistant(workspace_root=str(WORKSPACE_ROOT))

    if args.install_startup:
        print(assistant.install_startup())
        return 0

    if args.voice:
        if assistant._setup_voice():
            assistant.speak("Voice mode is ready. How can I help you?")
        else:
            assistant.speak("Voice packages are not available, so I will stay in text mode.")

    print("[offline-ai] Private assistant ready. No cloud or Ollama dependency.")
    print(f"Workspace root: {assistant.workspace_root}")

    if keyboard is not None and os.name == "nt":
        try:
            keyboard.add_hotkey("ctrl+alt+h", lambda: subprocess.Popen([sys.executable, str(assistant.workspace_root / "tray_launcher.py")]))
            print("Hotkey ready: Ctrl+Alt+H")
        except Exception as exc:
            print(f"Hotkey setup skipped: {exc}")

    if args.prompt:
        print(assistant.handle_command(args.prompt))
        return 0

    if args.file:
        try:
            if args.mode == "summarize":
                print(assistant.summarize_file(args.file))
            else:
                print(assistant.explain_file(args.file))
        except Exception as exc:
            print(f"[offline-ai] {exc}")
        return 0

    if args.auto:
        print("Auto mode enabled. Assistant is running.")
        while True:
            try:
                user_input = input("You> ").strip()
            except EOFError:
                break
            if not user_input:
                continue
            if user_input.startswith("!exit"):
                break
            assistant.speak(assistant.handle_command(user_input))
        return 0

    if os.name == "nt":
        try:
            ui = AssistantDesktopUI(assistant)
            ui.run()
            return 0
        except Exception as exc:
            print(f"[offline-ai] Desktop UI unavailable: {exc}")

    print("Type your request or use !help.")
    while True:
        try:
            if args.voice:
                user_input = assistant.listen_once()
                if user_input is None:
                    print("You> ")
                    user_input = input("You> ").strip()
                else:
                    print(f"You> {user_input}")
            else:
                user_input = input("You> ").strip()
        except EOFError:
            break

        if not user_input:
            continue

        if user_input.startswith("!help"):
            print_help()
            continue

        if user_input.startswith("!memory"):
            print(assistant.show_memory())
            continue

        if user_input.startswith("!summarize"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                print("Usage: !summarize <file>")
                continue
            try:
                print(assistant.summarize_file(parts[1]))
            except Exception as exc:
                print(f"[offline-ai] {exc}")
            continue

        if user_input.startswith("!explain"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                print("Usage: !explain <file>")
                continue
            try:
                print(assistant.explain_file(parts[1]))
            except Exception as exc:
                print(f"[offline-ai] {exc}")
            continue

        if user_input.startswith("!exit"):
            print("Goodbye.")
            break

        response = assistant.handle_command(user_input)
        assistant.speak(response)

    return 0


if __name__ == "__main__":
    sys.exit(main())
