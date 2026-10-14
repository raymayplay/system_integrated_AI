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
import asyncio
import datetime as dt
import email
import imaplib
import json
import os
import platform
import re
import shutil
import smtplib
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from difflib import get_close_matches
from email.header import decode_header
from email.message import EmailMessage
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote_plus
import tkinter as tk
from tkinter import messagebox, scrolledtext, filedialog, ttk

try:
    import keyboard  # type: ignore
except Exception:
    keyboard = None

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORKSPACE_ROOT = Path(os.getenv("LOCAL_AI_WORKSPACE", os.getcwd())).resolve()


class LocalPrivateAssistant:
    def __init__(self, workspace_root: str | None = None):
        self.workspace_root = Path(workspace_root or WORKSPACE_ROOT).resolve()
        self.memory_path = self.workspace_root / ".local_ai_memory.txt"
        self.memory = self._load_memory()
        self.voice_enabled = False
        self._speech_engine = None
        self._recognizer = None
        self._notification_lock = threading.Lock()
        self._notifications: List[str] = []
        self._inbox_monitor_thread: Optional[threading.Thread] = None
        self._inbox_monitor_stop: Optional[threading.Event] = None
        self.email_state_path = self.workspace_root / ".local_ai_email_state.json"
        self._email_state = self._load_email_state()
        self.auto_translate = False
        self.live_meeting_mode_active = False
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.selected_model = os.getenv("OLLAMA_MODEL", "qwen3:8b")

    def _load_memory(self) -> List[str]:
        if self.memory_path.exists():
            try:
                return [line.strip() for line in self.memory_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            except Exception:
                return []
        return []

    def _save_memory(self) -> None:
        self.memory_path.write_text("\n".join(self.memory) + "\n", encoding="utf-8")

    def _load_email_state(self) -> dict:
        if self.email_state_path.exists():
            try:
                return json.loads(self.email_state_path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_email_state(self) -> None:
        try:
            self.email_state_path.write_text(json.dumps(self._email_state), encoding="utf-8")
        except Exception:
            pass

    def _add_notification(self, message: str) -> None:
        with self._notification_lock:
            self._notifications.append(message)

    def pop_notifications(self) -> List[str]:
        with self._notification_lock:
            items = list(self._notifications)
            self._notifications.clear()
            return items

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

    def handle_send_email(self, prompt: str) -> str:
        direct = re.search(r"(?:send|email) email to ([^\n,]+?) subject ([^\n,]+?) body (.+)$", prompt, flags=re.I)
        if direct:
            recipient = direct.group(1).strip()
            subject = direct.group(2).strip()
            body = direct.group(3).strip()
            return self.send_email(recipient, subject, body)

        draft = re.search(r"(?:write|draft|send) email to ([^\n,]+?)(?: about| regarding) (.+)$", prompt, flags=re.I)
        if draft:
            recipient = draft.group(1).strip()
            topic = draft.group(2).strip()
            recipient_email = recipient
            subject = topic.title()
            body = (
                f"Hi {recipient.split()[0].title()},\n\n"
                f"I hope you are doing well. I am writing regarding {topic}. "
                "Please let me know your thoughts and next steps.\n\n"
                "Best regards,\nYour name"
            )
            return self.send_email(recipient_email, subject, body)

        return "To send email, say: send email to [recipient] subject [subject] body [message]."

    def handle_translation_request(self, prompt: str) -> str:
        text_match = re.search(r"translate(?: email| message)?(?: to english)?[:\s]*(.+)$", prompt, flags=re.I)
        if text_match:
            text_to_translate = text_match.group(1).strip()
            return self.translate_text(text_to_translate, "en")
        return "Please provide the text to translate. Example: translate email hello world to English."

    def handle_summarize_email(self, prompt: str) -> str:
        emails = self._fetch_unseen_emails(self.get_gmail_credentials() or {})
        if not emails:
            return "No unread email to summarize."
        email_data = emails[0]
        body = email_data.get("body", "")
        return f"Latest unread email from {email_data['from']} subject {email_data['subject']}: {self.summarize_email_text(body)}"

    def _launch_with_startfile(self, target: str) -> bool:
        if hasattr(os, "startfile"):
            try:
                os.startfile(target)
                return True
            except OSError:
                return False
        return False

    def _get_known_app_dirs(self) -> List[Path]:
        dirs: List[Path] = []
        if os.name == "nt":
            dirs += [
                Path(os.environ.get("ProgramFiles", "C:\\Program Files")),
                Path(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")),
                Path.home() / "AppData" / "Local" / "Programs",
                Path.home() / "AppData" / "Local" / "Microsoft" / "WindowsApps",
                Path.home() / "AppData" / "Local" / "Packages",
                Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
                Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
            ]
        return [path for path in dirs if path.exists()]

    def _normalize_installed_app_key(self, name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", name.lower()).strip()

    def discover_installed_apps(self) -> dict[str, Path]:
        if hasattr(self, "_installed_apps_cache"):
            return self._installed_apps_cache

        apps: dict[str, Path] = {}
        valid_extensions = {".exe", ".lnk", ".url", ".appref-ms"}
        for base_dir in self._get_known_app_dirs():
            try:
                for root, _, files in os.walk(base_dir):
                    for file_name in files:
                        extension = Path(file_name).suffix.lower()
                        if extension not in valid_extensions:
                            continue
                        file_path = Path(root) / file_name
                        key = self._normalize_installed_app_key(Path(file_name).stem)
                        if len(key) < 2:
                            continue
                        if key not in apps:
                            apps[key] = file_path
            except Exception:
                continue

        self._installed_apps_cache = apps
        return apps

    def find_installed_app_path(self, app_name: str) -> Optional[Path]:
        normalized = self._normalize_installed_app_key(app_name)
        apps = self.discover_installed_apps()
        if normalized in apps:
            return apps[normalized]

        candidates: List[tuple[float, str]] = []
        query_tokens = re.findall(r"[a-z0-9]+", normalized)
        for key, path in apps.items():
            if normalized == key:
                return apps[key]

            key_parts = [key, self._normalize_installed_app_key(path.stem), self._normalize_installed_app_key(path.parent.name)]
            score = 0
            if normalized in key:
                score += 100
            if key in normalized:
                score += 80
            if any(normalized in part for part in key_parts):
                score += 70
            if any(part in normalized for part in key_parts):
                score += 60

            if query_tokens and all(token in key for token in query_tokens):
                score += 50 + len(query_tokens) * 5

            if score > 0:
                candidates.append((score, key))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return apps[candidates[0][1]]

        match = get_close_matches(normalized, list(apps.keys()), n=1, cutoff=0.85)
        if match:
            return apps[match[0]]

        return None

    def list_installed_apps(self, max_entries: int = 50) -> List[str]:
        apps = sorted(self.discover_installed_apps().keys())
        return apps[:max_entries]

    def find_files(self, query: str, directory: str | None = None) -> List[str]:
        root = Path(directory or self.workspace_root).resolve()
        if not root.exists() or not root.is_dir():
            return []
        query_lower = query.lower()
        matches: List[str] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if query_lower in path.name.lower():
                try:
                    matches.append(str(path.relative_to(self.workspace_root)))
                except Exception:
                    matches.append(str(path))
            if len(matches) >= 50:
                break
        return matches

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
        known = {
            "firefox": ["firefox.exe", "C:\\Program Files\\Mozilla Firefox\\firefox.exe", "C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe"],
            "chrome": ["chrome.exe", "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"],
            "edge": ["msedge.exe", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"],
            "notepad": ["notepad.exe"],
            "calculator": ["calc.exe"],
            "terminal": ["wt.exe", "cmd.exe"],
            "windows terminal": ["wt.exe"],
            "cmd": ["cmd.exe"],
            "powershell": ["powershell.exe"],
            "explorer": ["explorer.exe"],
            "file explorer": ["explorer.exe"],
            "vscode": ["code.exe"],
            "visual studio code": ["code.exe"],
            "spotify": ["spotify.exe"],
            "teams": ["teams.exe"],
            "discord": ["discord.exe"],
            "zoom": ["zoom.exe"],
            "vlc": ["vlc.exe"],
            "word": ["winword.exe"],
            "excel": ["excel.exe"],
            "powerpoint": ["powerpnt.exe"],
            "onenote": ["onenote.exe"],
            "paint": ["mspaint.exe"],
            "wordpad": ["write.exe"],
            "control panel": ["control.exe"],
            "riot client": ["riot client.exe", "Riot Client.exe", "C:\\Riot Games\\Riot Client\\RiotClientServices.exe"],
            "riot games": ["riot client.exe", "Riot Client.exe", "C:\\Riot Games\\Riot Client\\RiotClientServices.exe"],
            "league client": ["leagueclient.exe", "C:\\Riot Games\\League of Legends\\LeagueClient.exe"],
            "spotify": [
                "spotify.exe",
                str(Path.home() / "AppData" / "Roaming" / "Spotify" / "Spotify.exe"),
            ],
        }

        if a in known:
            for candidate in known[a]:
                if os.path.exists(candidate) or shutil.which(candidate):
                    self._launch_with_startfile(candidate)
                    return f"Opened {app_name}."

        for candidate in [a, f"{a}.exe"]:
            if shutil.which(candidate):
                subprocess.Popen([candidate])
                return f"Opened {app_name}."
            if os.path.exists(candidate):
                self._launch_with_startfile(candidate)
                return f"Opened {app_name}."

        discovered = self.find_installed_app_path(a)
        if discovered is not None:
            if self._launch_with_startfile(str(discovered)):
                return f"Opened {app_name} from installed apps."
            try:
                subprocess.Popen([str(discovered)])
                return f"Opened {app_name} from installed apps."
            except Exception:
                pass

        if self._launch_with_startfile(app_name):
            return f"Opened {app_name}."

        if os.name == "nt" and a == "spotify":
            try:
                self._launch_with_startfile("spotify:")
                return f"Opened {app_name}."
            except Exception:
                pass

        if os.name == "nt":
            try:
                subprocess.run(["cmd", "/c", "start", "", app_name], shell=False, check=False)
                return f"Opened {app_name}."
            except Exception:
                pass

        return f"I could not find or open {app_name} on this PC. Try a more specific app name or use 'list apps'."

    def download_app(self, app_name: str) -> str:
        a = self._normalize_app_name(f"download {app_name}")
        direct_downloads = {
            "spotify": ("https://download.scdn.co/SpotifySetup.exe", "SpotifySetup.exe"),
            "vscode": ("https://update.code.visualstudio.com/latest/win32-x64-user/stable", "VSCodeSetup.exe"),
            "firefox": ("https://download.mozilla.org/?product=firefox-latest-ssl&os=win&lang=en-US", "FirefoxInstaller.exe"),
            "zoom": ("https://zoom.us/client/latest/ZoomInstaller.exe", "ZoomInstaller.exe"),
            "vlc": ("https://get.videolan.org/vlc/last/win64/vlc-64-bit.exe", "VLCInstaller.exe"),
        }
        download_pages = {
            "chrome": "https://www.google.com/chrome/",
            "teams": "https://www.microsoft.com/en-us/microsoft-teams/download-app",
            "discord": "https://discord.com/download",
            "slack": "https://slack.com/downloads/windows",
            "spotify": "https://www.spotify.com/download/windows/",
            "vscode": "https://code.visualstudio.com/Download",
            "firefox": "https://www.mozilla.org/firefox/new/",
        }

        if a in direct_downloads:
            url, filename = direct_downloads[a]
            target = Path(tempfile.gettempdir()) / filename
            try:
                urllib.request.urlretrieve(url, target)
                subprocess.Popen([str(target)])
                return f"Downloaded {app_name} installer to {target} and started it. Follow the installer prompts to complete installation."
            except Exception as exc:
                return f"I could not download {app_name}: {exc}"

        if a in download_pages:
            webbrowser.open(download_pages[a])
            return f"Opened the download page for {app_name}. Please follow the website instructions to install it."

        search_url = f"https://www.google.com/search?q=download+{quote_plus(app_name)}+windows"
        webbrowser.open(search_url)
        return f"I could not download {app_name} directly, but I opened a search page to help you find the installer."

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
            return "No email credentials found. Create gmail_credentials.json with email, password, and optional IMAP/SMTP settings to enable inbox reading and sending."
        return (
            f"Email access is configured for {credentials['email']} on {credentials.get('imap_server', 'imap.gmail.com')}. "
            "This local app can check your inbox and send mail from your account."
        )

    def _decode_mime_words(self, value: str) -> str:
        decoded = ""
        for part, encoding in decode_header(value):
            if isinstance(part, bytes):
                try:
                    decoded += part.decode(encoding or "utf-8", errors="ignore")
                except Exception:
                    decoded += part.decode("utf-8", errors="ignore")
            else:
                decoded += str(part)
        return decoded

    def _get_email_body(self, msg: email.message.Message) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))
                if content_type == "text/plain" and "attachment" not in disposition:
                    try:
                        return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
                    except Exception:
                        continue
        else:
            try:
                return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="ignore")
            except Exception:
                return str(msg.get_payload())
        return ""

    def _connect_imap(self, credentials: dict[str, str]) -> imaplib.IMAP4_SSL:
        imap_server = credentials.get("imap_server", "imap.gmail.com")
        imap_port = int(credentials.get("imap_port", 993))
        imap = imaplib.IMAP4_SSL(imap_server, imap_port)
        imap.login(credentials["email"], credentials["password"])
        return imap

    def _connect_smtp(self, credentials: dict[str, str]) -> smtplib.SMTP:
        smtp_server = credentials.get("smtp_server", "smtp.gmail.com")
        smtp_port = int(credentials.get("smtp_port", 587))
        smtp = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
        smtp.starttls()
        smtp.login(credentials["email"], credentials["password"])
        return smtp

    def _fetch_unseen_emails(self, credentials: dict[str, str]) -> List[dict[str, str]]:
        try:
            imap = self._connect_imap(credentials)
            imap.select("INBOX")
            status, messages = imap.search(None, "UNSEEN")
            if status != "OK":
                imap.logout()
                return []
            unseen = messages[0].split()
            emails: List[dict[str, str]] = []
            for num in unseen[-10:]:
                status, data = imap.fetch(num, "RFC822")
                if status != "OK" or not data or not data[0]:
                    continue
                msg = email.message_from_bytes(data[0][1])
                sender = self._decode_mime_words(msg.get("From", "Unknown sender"))
                subject = self._decode_mime_words(msg.get("Subject", "(no subject)"))
                date = msg.get("Date", "")
                body = self._get_email_body(msg).strip()
                emails.append({"from": sender, "subject": subject, "date": date, "body": body})
            imap.logout()
            return emails
        except Exception:
            return []

    def check_inbox(self) -> str:
        credentials = self.get_gmail_credentials()
        if credentials is None:
            return "No email credentials found. Create gmail_credentials.json with email and password to enable inbox access."

        emails = self._fetch_unseen_emails(credentials)
        if not emails:
            return "No new email found."

        summaries = []
        for email_data in emails[:5]:
            summary = f"From: {email_data['from']}\nSubject: {email_data['subject']}"
            if email_data["body"]:
                preview = email_data["body"].replace("\n", " ")
                summaries.append(f"{summary}\nPreview: {preview[:180]}...")
            else:
                summaries.append(summary)

        self._email_state["last_checked"] = dt.datetime.utcnow().isoformat()
        self._save_email_state()
        return "New emails:\n\n" + "\n\n".join(summaries)

    def send_email(self, recipient: str, subject: str, body: str) -> str:
        credentials = self.get_gmail_credentials()
        if credentials is None:
            return "No email credentials found. Create gmail_credentials.json with email and password to enable sending."
        try:
            message = EmailMessage()
            message["From"] = credentials["email"]
            message["To"] = recipient
            message["Subject"] = subject
            message.set_content(body)
            smtp = self._connect_smtp(credentials)
            smtp.send_message(message)
            smtp.quit()
            return f"Email sent to {recipient} with subject '{subject}'."
        except Exception as exc:
            return f"Failed to send email: {exc}"

    def recommend_language(self, user_input: str | None = None, context: str = "general") -> dict[str, str]:
        text = (user_input or "").strip().lower()
        language_map = {
            "english": {"code": "en", "name": "English", "reason": "Best for general meetings, emails, and global collaboration."},
            "spanish": {"code": "es", "name": "Spanish", "reason": "Good for conversational meetings and fast bilingual notes."},
            "french": {"code": "fr", "name": "French", "reason": "Useful for European business and meeting follow-ups."},
            "german": {"code": "de", "name": "German", "reason": "Helpful for technical or business meetings with German-speaking teams."},
            "portuguese": {"code": "pt", "name": "Portuguese", "reason": "Useful for international project updates and client communication."},
            "italian": {"code": "it", "name": "Italian", "reason": "Helpful for meetings with Italian-speaking stakeholders."},
            "arabic": {"code": "ar", "name": "Arabic", "reason": "Strong for bilingual global conversations and notes."},
            "hindi": {"code": "hi", "name": "Hindi", "reason": "Ideal for Indian business and meeting summaries."},
            "japanese": {"code": "ja", "name": "Japanese", "reason": "Helpful for technical notes and international coordination."},
            "korean": {"code": "ko", "name": "Korean", "reason": "Useful for collaboration with Korean partners or teams."},
        }

        if not text:
            preferred = "english" if "meeting" in context.lower() else "english"
            return language_map[preferred]

        normalized = re.sub(r"[^a-z]+", " ", text)
        for name, info in language_map.items():
            if name in normalized or info["name"].lower() in normalized:
                return info

        if any(term in normalized for term in ["spanish", "espanol", "es"]):
            return language_map["spanish"]
        if any(term in normalized for term in ["french", "francais", "fr"]):
            return language_map["french"]
        if any(term in normalized for term in ["german", "deutsch", "de"]):
            return language_map["german"]
        if any(term in normalized for term in ["portuguese", "portugues", "pt"]):
            return language_map["portuguese"]
        if any(term in normalized for term in ["arabic", "arabic", "ar"]):
            return language_map["arabic"]
        if any(term in normalized for term in ["hindi", "hi"]):
            return language_map["hindi"]
        if any(term in normalized for term in ["japanese", "japonese", "ja"]):
            return language_map["japanese"]
        if any(term in normalized for term in ["korean", "ko"]):
            return language_map["korean"]

        return language_map["english"]

    def summarize_meeting(self, transcript: str, language: str = "en") -> str:
        text = (transcript or "").strip()
        if not text:
            return "No meeting transcript was provided. Paste the meeting notes or transcript and I will summarize it."

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        sentences = []
        for line in lines:
            if ":" in line:
                _, body = line.split(":", 1)
                sentence = body.strip()
            else:
                sentence = line
            if sentence:
                sentences.extend([part.strip() for part in re.split(r"(?<=[.!?])\s+", sentence) if part.strip()])

        if not sentences:
            sentences = [text]

        objective = next(
            (s for s in sentences if any(keyword in s.lower() for keyword in ["launch", "goal", "plan", "project", "priority", "decision", "need", "must", "should", "target"])),
            sentences[0],
        )

        action_items = [
            s for s in sentences if any(keyword in s.lower() for keyword in ["next", "action", "follow up", "deliver", "deadline", "due", "fix", "update", "must", "need to", "should", "plan", "launch"])
        ]
        if not action_items:
            action_items = sentences[:3]

        risks = [
            s for s in sentences if any(keyword in s.lower() for keyword in ["risk", "problem", "issue", "delay", "cost", "budget", "concern", "challenge", "slow", "error"])
        ]
        if not risks:
            risks = ["No major blockers were identified in the transcript."]

        decisions = [
            s for s in sentences if any(keyword in s.lower() for keyword in ["decision", "agreed", "approved", "confirmed", "will", "we decided", "we agreed", "go ahead", "launch"])
        ]
        if not decisions:
            decisions = ["The team aligned on the core direction and sequencing of the work."]

        language_label = self.recommend_language(language, context="meeting")["name"]
        if language.lower() not in {"en", "english"}:
            translated_summary = self.translate_text(
                (
                    "Meeting summary:\n"
                    f"- Main topic: {objective}\n"
                    f"- Key decisions: {'; '.join(decisions[:2])}\n"
                    f"- Action items: {'; '.join(action_items[:3])}\n"
                    f"- Risks: {'; '.join(risks[:2])}"
                ),
                language,
            )
            return translated_summary

        return (
            "Meeting summary:\n"
            f"- Main topic: {objective}\n"
            f"- Key decisions: {'; '.join(decisions[:2])}\n"
            f"- Action items: {'; '.join(action_items[:3])}\n"
            f"- Risks/concerns: {'; '.join(risks[:2])}\n"
            f"- Recommended language: {language_label}"
        )

    def translate_text(self, text: str, target_language: str = "en") -> str:
        if not text or not text.strip():
            return "Please provide text to translate."

        target = (target_language or "en").strip().lower()
        language_code = {
            "en": "en",
            "english": "en",
            "es": "es",
            "spanish": "es",
            "espanol": "es",
            "fr": "fr",
            "french": "fr",
            "de": "de",
            "german": "de",
            "deutsch": "de",
            "pt": "pt",
            "portuguese": "pt",
            "it": "it",
            "italian": "it",
            "ar": "ar",
            "arabic": "ar",
            "hi": "hi",
            "hindi": "hi",
            "ja": "ja",
            "japanese": "ja",
            "ko": "ko",
            "korean": "ko",
        }
        final_target = language_code.get(target, target)
        if final_target == "ja":
            common_phrases = {
                "i like you": "私はあなたが好きです",
                "i love you": "愛してる",
            }
            normalized_text = re.sub(r"\s+", " ", text.strip().lower()).rstrip(".!?")
            if normalized_text in common_phrases:
                return common_phrases[normalized_text]

        try:
            from googletrans import Translator  # type: ignore
        except Exception:
            pass
        else:
            try:
                translator = Translator()
                result = translator.translate(text, dest=final_target)
                if asyncio.iscoroutine(result):
                    result = asyncio.run(result)
                if hasattr(result, "text"):
                    return result.text
                if isinstance(result, str):
                    return result
            except Exception:
                pass

        phrase_map = {
            "en": {
                "hello": "hello",
                "hi": "hi",
                "team": "team",
                "meeting": "meeting",
                "project": "project",
                "today": "today",
                "important": "important",
                "deadline": "deadline",
                "task": "task",
                "thanks": "thanks",
                "yes": "yes",
                "no": "no",
                "good": "good",
                "morning": "morning",
                "afternoon": "afternoon",
                "evening": "evening",
                "please": "please",
                "next": "next",
                "step": "step",
                "action": "action",
                "decision": "decision",
                "cost": "cost",
                "budget": "budget",
                "launch": "launch",
                "customer": "customer",
            },
            "es": {
                "hello": "hola",
                "hi": "hola",
                "team": "equipo",
                "meeting": "reunión",
                "project": "proyecto",
                "today": "hoy",
                "important": "importante",
                "deadline": "fecha límite",
                "task": "tarea",
                "thanks": "gracias",
                "yes": "sí",
                "no": "no",
                "good": "bueno",
                "morning": "mañana",
                "afternoon": "tarde",
                "evening": "noche",
                "please": "por favor",
                "next": "próximo",
                "step": "paso",
                "action": "acción",
                "decision": "decisión",
                "cost": "costo",
                "budget": "presupuesto",
                "launch": "lanzamiento",
                "customer": "cliente",
            },
            "fr": {
                "hello": "bonjour",
                "hi": "salut",
                "team": "équipe",
                "meeting": "réunion",
                "project": "projet",
                "today": "aujourd'hui",
                "important": "important",
                "deadline": "date limite",
                "task": "tâche",
                "thanks": "merci",
                "yes": "oui",
                "no": "non",
                "good": "bon",
                "morning": "matin",
                "afternoon": "après-midi",
                "evening": "soir",
                "please": "s'il vous plaît",
                "next": "suivant",
                "step": "étape",
                "action": "action",
                "decision": "décision",
                "cost": "coût",
                "budget": "budget",
                "launch": "lancement",
                "customer": "client",
            },
            "de": {
                "hello": "hallo",
                "hi": "hallo",
                "team": "team",
                "meeting": "besprechung",
                "project": "projekt",
                "today": "heute",
                "important": "wichtig",
                "deadline": "frist",
                "task": "aufgabe",
                "thanks": "danke",
                "yes": "ja",
                "no": "nein",
                "good": "gut",
                "morning": "morgen",
                "afternoon": "nachmittag",
                "evening": "abend",
                "please": "bitte",
                "next": "nächste",
                "step": "schritt",
                "action": "maßnahme",
                "decision": "entscheidung",
                "cost": "kosten",
                "budget": "budget",
                "launch": "start",
                "customer": "kunde",
            },
            "pt": {
                "hello": "olá",
                "hi": "oi",
                "team": "equipe",
                "meeting": "reunião",
                "project": "projeto",
                "today": "hoje",
                "important": "importante",
                "deadline": "prazo",
                "task": "tarefa",
                "thanks": "obrigado",
                "yes": "sim",
                "no": "não",
                "good": "bom",
                "morning": "manhã",
                "afternoon": "tarde",
                "evening": "noite",
                "please": "por favor",
                "next": "próximo",
                "step": "etapa",
                "action": "ação",
                "decision": "decisão",
                "cost": "custo",
                "budget": "orçamento",
                "launch": "lançamento",
                "customer": "cliente",
            },
            "ja": {
                "hello": "こんにちは",
                "hi": "こんにちは",
                "team": "チーム",
                "meeting": "会議",
                "project": "プロジェクト",
                "today": "今日",
                "important": "重要",
                "deadline": "締切",
                "task": "タスク",
                "thanks": "ありがとう",
                "yes": "はい",
                "no": "いいえ",
                "good": "良い",
                "morning": "朝",
                "afternoon": "午後",
                "evening": "夕方",
                "please": "お願いします",
                "next": "次",
                "step": "ステップ",
                "action": "アクション",
                "decision": "決定",
                "cost": "コスト",
                "budget": "予算",
                "launch": "開始",
                "customer": "顧客",
            },
        }

        word_map = phrase_map.get(final_target, phrase_map.get("en", {}))
        if not word_map:
            return text

        original_words = re.findall(r"\b[\w']+\b|[^\w\s]", text)
        translated = []
        for token in original_words:
            normalized = token.lower().strip("'\"")
            if normalized in word_map:
                translated.append(word_map[normalized])
            elif token.strip() and token.strip() not in {" ", "\n", "\t"}:
                translated.append(token)
        translated_text = "".join(translated)
        if translated_text.strip() == text.strip():
            return f"Translation target '{target_language}' is available in local quick mode for common meeting phrases. Full language models can be enabled with an API key."
        return translated_text

    def compose_email(self, prompt: str) -> tuple[str, str, str]:
        match = re.search(r"(?:write|draft|send) email to ([^\n,]+?)\s*(?:about|regarding)\s+(.+)$", prompt, flags=re.I)
        if match:
            recipient = match.group(1).strip()
            topic = match.group(2).strip()
            subject = topic.title()
            name = self._normalize(credentials.get("email", "").split("@")[0]) if (credentials := self.get_gmail_credentials()) else "there"
            body = (
                f"Hi {recipient.split()[0].title()},\n\n"
                f"I hope you are doing well. I wanted to reach out about {topic}. "
                "Please let me know your thoughts and next steps.\n\n"
                "Best regards,\n"
                f"{name.title()}"
            )
            return recipient, subject, body
        return "", "", ""

    def start_inbox_monitor(self, interval_seconds: int = 300) -> None:
        if self._inbox_monitor_thread and self._inbox_monitor_thread.is_alive():
            return
        if self.get_gmail_credentials() is None:
            return

        self._inbox_monitor_stop = threading.Event()

        def monitor() -> None:
            while not self._inbox_monitor_stop.is_set():
                message = self.check_inbox()
                if message and not message.startswith("No new email"):
                    self._add_notification(message)
                self._inbox_monitor_stop.wait(interval_seconds)

        self._inbox_monitor_thread = threading.Thread(target=monitor, daemon=True)
        self._inbox_monitor_thread.start()

    def stop_inbox_monitor(self) -> None:
        if self._inbox_monitor_stop:
            self._inbox_monitor_stop.set()
        return (
            f"Platform: {platform.platform()}\n"
            f"System: {platform.system()} {platform.release()}\n"
            f"CPU: {platform.processor() or 'unknown'}\n"
            f"Python: {platform.python_version()}"
        )

    def open_file_in_default_app(self, file_path: str) -> str:
        path = self._resolve_path(file_path)
        if not path.exists():
            matches = self.find_files(file_path, str(self.workspace_root))
            if len(matches) == 1:
                path = self.workspace_root / matches[0]
            elif matches:
                return "Found matching files:\n- " + "\n- ".join(matches[:25])
            else:
                return f"File not found: {path}"

        if self._launch_with_startfile(str(path)):
            return f"Opened file: {path}"
        return f"Could not open file: {path}"

    def run_shell_command(self, command: str) -> str:
        if not command.strip():
            return "Please provide a command to run."
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=20)
            output = result.stdout.strip() or result.stderr.strip()
            if not output:
                return f"Command completed: {command}"
            return output
        except subprocess.TimeoutExpired:
            return "The command timed out."
        except Exception as exc:
            return f"Command failed: {exc}"

    def auto_correct_text(self, text: str) -> str:
        replacements = {
            "opne": "open",
            "opn": "open",
            "oprn": "open",
            "lauch": "launch",
            "launh": "launch",
            "caluclator": "calculator",
            "firefoz": "firefox",
            "firefow": "firefox",
            "firefoc": "firefox",
            "notepadd": "notepad",
            "setings": "settings",
            "gmails": "gmail",
            "youtub": "youtube",
            "poweshell": "powershell",
            "terminall": "terminal",
            "explorrer": "explorer",
            "cmds": "cmd",
            "runing": "run",
            "runn": "run",
            "zomm": "zoom",
            "zoomm": "zoom",
        }
        tokens = text.split()
        corrected = []
        for token in tokens:
            lower = token.lower()
            if lower in replacements:
                corrected.append(replacements[lower])
            else:
                match = get_close_matches(lower, replacements.keys(), n=1, cutoff=0.9)
                if match:
                    corrected.append(replacements[match[0]])
                else:
                    corrected.append(token)
        return " ".join(corrected)

    def is_wake_word(self, text: str) -> bool:
        normalized = self._normalize(text)
        wake_phrases = [
            "hey ray",
            "hello ray",
            "hi ray",
            "ray",
            "hey ai",
            "hello ai",
            "hey assistant",
            "hello assistant",
        ]
        return any(phrase in normalized for phrase in wake_phrases)

    def split_command_sequence(self, text: str) -> List[str]:
        cleaned = text.strip()
        if not cleaned:
            return []
        parts = re.split(r"\s+and\s+|\s*;\s*|\s*then\s+", cleaned, flags=re.I)
        normalized = []
        for part in parts:
            part = part.strip()
            if part:
                normalized.append(part)
        return normalized

    def process_command_sequence(self, prompt: str) -> str:
        commands = self.split_command_sequence(prompt)
        if len(commands) <= 1:
            return self.handle_command(prompt)

        responses = []
        for command in commands:
            response = self.handle_command(command)
            if response:
                responses.append(response)
        return "\n\n".join(responses)

    def matches_any(self, text: str, phrases: List[str]) -> bool:
        lowered = self._normalize(text)
        for phrase in phrases:
            pattern = r"(?<![a-z0-9])" + re.escape(self._normalize(phrase)) + r"(?![a-z0-9])"
            if re.search(pattern, lowered):
                return True
        return False

    def listen_for_wake_word(self, timeout_seconds: int = 10) -> Optional[str]:
        if not self.voice_enabled or self._recognizer is None:
            return None
        try:
            import speech_recognition as sr  # type: ignore
        except ImportError:
            return None

        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio = self._recognizer.listen(source, timeout=timeout_seconds, phrase_time_limit=5)
            return self._recognizer.recognize_sphinx(audio)
        except Exception:
            return None

    def listen_for_command_after_wake(self) -> Optional[str]:
        if not self.voice_enabled or self._recognizer is None:
            return None
        try:
            import speech_recognition as sr  # type: ignore
        except ImportError:
            return None

        try:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
                audio = self._recognizer.listen(source, timeout=12, phrase_time_limit=8)
            return self._recognizer.recognize_sphinx(audio)
        except Exception:
            return None

    def translate_japanese(self, text: str) -> str:
        if not text or not text.strip():
            return "翻訳する文章を教えてください。"
        if self.translate_text(text, "ja") == text:
            return "日本語への翻訳が利用できません。英語の音声またはテキストを追加してください。"
        return self.translate_text(text, "ja")

    def translate_english(self, text: str) -> str:
        if not text or not text.strip():
            return "翻訳する文章を教えてください。"
        return self.translate_text(text, "en")

    def live_meeting_mode(self) -> str:
        if not self.voice_enabled:
            return "Microphone is not enabled yet. Turn on voice mode first."

        self.live_meeting_mode_active = True
        self.auto_translate = True
        self.speak("Live meeting mode is active. Say 'hey ray' to wake me or say 'stop' to exit.")
        while True:
            wake_text = self.listen_for_wake_word(timeout_seconds=15)
            if not wake_text:
                continue
            if not self.is_wake_word(wake_text):
                continue
            self.speak("I'm ready. What do you need?")
            command = self.listen_for_command_after_wake()
            if not command:
                self.speak("I could not hear the command clearly.")
                continue

            user_text = command.strip()
            lower = user_text.lower()
            if any(keyword in lower for keyword in ["stop", "終了", "やめて", "quit"]):
                self.live_meeting_mode_active = False
                self.auto_translate = False
                self.speak("Live meeting mode is off.")
                return "Live meeting mode is off."

            response = self.handle_command(user_text)
            self.speak(response)
            if self.auto_translate and user_text:
                translated = self.translate_japanese(user_text) if any(ch in user_text for ch in "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん") else self.translate_english(user_text)
                if translated and translated != user_text:
                    self.speak(f"Translation: {translated}")

    def list_directory_contents(self, directory: str) -> List[str]:
        path = Path(directory).expanduser()
        if not path.is_absolute():
            path = (self.workspace_root / path).resolve()

        if not path.exists():
            special = self.resolve_special_target(directory)
            if special and special[0] == "folder":
                path = Path(special[1]).expanduser()

        if not path.exists() and not Path(directory).is_absolute():
            path = Path.home() / directory

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

    def ask_local_ollama(self, prompt: str, model: str | None = None) -> str:
        if not prompt or not prompt.strip():
            return ""

        local_model = model or self.selected_model or os.getenv("OLLAMA_MODEL")
        if not local_model:
            try:
                models = self.list_ollama_models()
            except RuntimeError as exc:
                return str(exc)
            if not models:
                return "No local Ollama models are installed. Install Ollama and pull a model, then select it here."
            local_model = models[0]

        payload = {
            "model": local_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3},
        }

        try:
            request = urllib.request.Request(
                f"{self.ollama_base_url}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, dict):
                return f"Ollama returned an invalid response for model {local_model}."
            text = data.get("response", "").strip()
            if text:
                return text
            return "Ollama returned an empty response. Check the selected model and try again."
        except (OSError, ValueError, urllib.error.URLError) as exc:
            return f"Could not get a response from local Ollama ({local_model}): {exc}"

    def list_ollama_models(self) -> List[str]:
        request = urllib.request.Request(f"{self.ollama_base_url}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise RuntimeError(
                f"Ollama is not responding at {self.ollama_base_url}. Start Ollama and refresh models. ({exc})"
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError("Ollama returned an invalid model list.")
        models = data.get("models")
        if not isinstance(models, list):
            raise RuntimeError("Ollama returned an invalid model list.")
        return [
            model["name"]
            for model in models
            if isinstance(model, dict) and isinstance(model.get("name"), str)
        ]

    def should_use_local_llm(self, prompt: str) -> bool:
        lower = self._normalize(prompt)
        if any(token in lower for token in ["summarize", "summary", "explain", "plan", "strategy", "brainstorm", "draft", "creative", "compare", "analysis", "research"]):
            return True
        if any(token in lower for token in ["what do you think", "can you help me with", "give me ideas", "how should i", "why is", "what is the best", "advice", "should i", "launch plan", "startup", "business", "marketing"]):
            return True
        if len(lower) >= 80:
            return True
        return False

    def ask_advanced_ai(self, prompt: str) -> str:
        if not self.should_use_local_llm(prompt):
            return ""

        if os.getenv("LOCAL_AI_USE_REMOTE", "0").lower() in {"1", "true", "yes", "on"}:
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                return self.ask_local_ollama(prompt)
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            }
            try:
                request = urllib.request.Request(base_url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=20) as response:
                    data = json.loads(response.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
            except Exception:
                pass

        return self.ask_local_ollama(prompt)

    def install_startup(self) -> str:
        if os.name != "nt":
            raise RuntimeError("Automatic startup shortcuts are supported only on Windows.")
        appdata = os.getenv("APPDATA")
        if not appdata:
            raise RuntimeError("The Windows APPDATA folder is unavailable.")
        startup_dir = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        startup_dir.mkdir(parents=True, exist_ok=True)
        startup_script = startup_dir / "Ray Assistant.cmd"
        for obsolete_name in ("pew_assistant.lnk", "handleai_tray.lnk", "ray_startup.cmd", "Ray Assistant.lnk"):
            obsolete_entry = startup_dir / obsolete_name
            if obsolete_entry.exists():
                obsolete_entry.unlink()
        launcher_path = self.workspace_root / "start_assistant.cmd"
        if not launcher_path.exists():
            raise RuntimeError(f"Ray startup launcher was not found: {launcher_path}")
        startup_script.write_text(
            "@echo off\r\n"
            f'start "" "{launcher_path}"\r\n',
            encoding="utf-8",
        )
        return f"Installed Ray auto-start at {startup_script}"

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
        if any(normalized.startswith(prefix) for prefix in ["open file ", "read file ", "show file ", "open folder ", "list folder ", "show folder ", "open website ", "visit "]):
            return False
        if re.search(r"(?i)\b(make me feel special|feel special|make me feel loved|make me feel happy|compliment me|make me happy)\b", normalized):
            return False
        app_terms = ["firefox", "chrome", "edge", "notepad", "calculator", "settings", "gmail", "youtube", "spotify", "vscode", "terminal", "cmd", "powershell", "explorer", "word", "excel", "powerpoint", "teams", "discord", "vlc", "zoom", "onedrive", "paint", "wordpad"]
        tokens = self._normalize_tokens(normalized)
        for token in tokens:
            if token in app_terms:
                return True
            if get_close_matches(token, app_terms, n=1, cutoff=0.65):
                return True
        if normalized.startswith(("open ", "launch ", "start ", "run ", "go to ", "goto ")) and len(tokens) > 1:
            return True
        return False

    def _normalize_app_name(self, prompt: str) -> str:
        normalized = self._normalize(prompt)
        phrase = normalized

        phrase = re.sub(r"(?i)^(?:can you|could you|would you|can u|could u|please|kindly)\s+", "", phrase)
        for prefix in ["open", "launch", "start", "run", "go to", "goto"]:
            if phrase.startswith(prefix + " "):
                phrase = phrase[len(prefix) + 1 :].strip()
                break

        phrase = re.sub(r"(?i)\s+(?:for me|please|now)\s*$", "", phrase)
        phrase = re.sub(r"(?i)\b(?:can|could|would|you|u|me|please|for|to)\b", " ", phrase)
        phrase = re.sub(r"\s+", " ", phrase).strip()

        if not phrase:
            return ""

        if re.search(r"(?i)\briot\b.*\b(game|games|client)\b|\briot\s*(?:game|games|client)\b", phrase):
            return "riot client"
        if re.search(r"(?i)\bleague\b.*\bclient\b|\bleague\s*client\b", phrase):
            return "league client"

        tokens = self._normalize_tokens(phrase)
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
            "riotgames": "riot client",
            "riotgamesclient": "riot client",
            "riotclient": "riot client",
            "riot": "riot client",
            "league": "league client",
        }
        app_terms = [
            "firefox",
            "chrome",
            "edge",
            "notepad",
            "calculator",
            "settings",
            "gmail",
            "youtube",
            "spotify",
            "vscode",
            "terminal",
            "cmd",
            "powershell",
            "explorer",
            "word",
            "excel",
            "powerpoint",
            "steam",
            "discord",
            "vlc",
            "zoom",
            "onedrive",
            "paint",
            "wordpad",
            "riot client",
            "riot games",
            "league client",
        ]

        for token in tokens:
            normalized_token = aliases.get(token, token)
            if normalized_token in app_terms:
                return normalized_token
            match = get_close_matches(normalized_token, app_terms, n=1, cutoff=0.75)
            if match:
                return match[0]

        if phrase:
            return phrase

    def handle_command(self, prompt: str) -> str:
        if not prompt.strip():
            return "What can I help you with?"

        prompt = self.auto_correct_text(prompt)
        p = self._normalize(prompt)

        if self.is_wake_word(prompt):
            prompt = re.sub(r"(?i)\b(hey|hello|hi)\s*(ray|ai|assistant)\b", "", prompt).strip()
            if prompt:
                return self.handle_command(prompt)
            return "Yes? I'm ready."

        local_ai_request = re.match(r"(?is)^/ai\s+(.+)$", prompt)
        if local_ai_request:
            return self.ask_local_ollama(local_ai_request.group(1).strip())

        if self.matches_any(prompt, ["can you really do it", "do you have access to my pc", "access to my pc", "server", "cloud only", "are you remote", "do you run on a server"]):
            return "Yes — I am built to run locally on your PC, not only in a remote server. I can open apps, read local files, search the web, and translate text when you ask."

        if re.search(r"(?i)\b(make me feel special|feel special|make me feel loved|make me feel happy|compliment me|make me happy)\b", prompt):
            return "Absolutely — you are special, and I want you to feel that. You bring real thought, heart, and value to the room, and I’m glad you’re here."

        if re.search(r"(?i)\b(bro|bruh|yo|dude)\b", prompt):
            return "Bro, I'm here. I can help with your PC, open apps, summarize meetings, and translate text when you ask."

        phrase_translation = re.search(r"(?:what is|what's|how do you say|say|translate)\s+(.+?)\s+(?:in|to)\s+(english|japanese)\b", prompt, flags=re.I)
        if phrase_translation:
            text = phrase_translation.group(1).strip().strip("\"'")
            target = phrase_translation.group(2).lower()
            if target.startswith("j"):
                return self.translate_japanese(text)
            return self.translate_english(text)

        if self.matches_any(prompt, ["translate to japanese", "translate hello", "日本語に翻訳", "to japanese", "japanese translation", "translate to english", "英語に翻訳", "to english", "translate email", "translate message", "live meeting", "meeting mode", "ミーティング翻訳", "リアルタイム", "meeting live"]):
            if self.matches_any(prompt, ["live meeting", "meeting mode", "ミーティング翻訳", "リアルタイム", "meeting live"]):
                return self.live_meeting_mode()
            if self.matches_any(prompt, ["translate to japanese", "日本語に翻訳", "to japanese", "japanese translation"]):
                target = re.sub(r"(?i)^(translate|translation)\s+", "", prompt).strip()
                target = re.sub(r"(?i)\b(to\s+japanese|japanese|日本語に翻訳|日本語で)\b", "", target).strip()
                if not target:
                    target = prompt
                return self.translate_japanese(target)
            if self.matches_any(prompt, ["translate to english", "英語に翻訳", "to english", "english translation"]):
                target = re.sub(r"(?i)^(translate|translation)\s+", "", prompt).strip()
                target = re.sub(r"(?i)\b(to\s+english|english|英語に翻訳|英語で)\b", "", target).strip()
                if not target:
                    target = prompt
                return self.translate_english(target)
            if self.matches_any(prompt, ["translate email", "translate message", "email translation", "message translation"]):
                return self.handle_translation_request(prompt)

        if re.search(r"(?i)\b(?:can you|could you|would you)\s+translate\b", prompt):
            target = re.sub(r"(?i)^(?:can you|could you|would you)\s+", "", prompt).strip()
            target = re.sub(r"(?i)^translate\s+", "", target).strip()
            if target:
                if re.search(r"(?i)\b(?:english|japanese)\b", target):
                    if "japanese" in target.lower():
                        return self.translate_japanese(target.replace("japanese", "", 1).strip())
                    if "english" in target.lower():
                        return self.translate_english(target.replace("english", "", 1).strip())
                return self.translate_japanese(target) if "love you" in target.lower() else self.translate_english(target)
            return "Please tell me what to translate."

        if re.search(r"(?i)\b(ollama|local model|model is not working|doing nothing|not responding|why is ollama|ollama not)\b", prompt):
            return "Ollama is local and can fail if the model is not installed or the service is not running. I can help you check the model, restart the local server, and confirm whether the request is valid."

        if any(token in p for token in ["hello", "hi", "hey", "こんにちは", "おはよう", "こんばんは"]):
            return "Hello, I am Ray. I can open apps, summarize meetings, and translate between English and Japanese when you ask."

        if any(token in p for token in ["what can you do", "help", "何ができますか", "使い方", "ヘルプ"]):
            return "I can open apps, search the web, summarize meetings, manage notes, and translate English and Japanese when you ask. You can say 'hey ray' to activate me by voice."

        if any(token in p for token in ["joke", "funny", "humor"]):
            return "Of course. Why did the robot bring a ladder? To reach new heights, obviously."

        if any(token in p for token in ["こんにちは", "おはよう", "こんばんは", "やぁ", "ええ"]):
            return "こんにちは。ミーティングの要点の要約、翻訳、アプリ起動をお手伝いします。"

        if self.matches_any(prompt, ["live meeting", "meeting live", "translate live", "リアルタイム", "live translation", "ライブ会議", "ミーティング翻訳", "meeting mode"]):
            return self.live_meeting_mode()

        if self.matches_any(prompt, ["日本語", "japanese", "translate to japanese", "japanese translation", "日本語に翻訳", "to japanese"]):
            target = prompt
            for prefix in ["translate", "translation", "日本語に翻訳", "japanese", "translate to japanese", "to japanese", "日本語で"]:
                target = target.replace(prefix, "", 1).strip()
            if target:
                return self.translate_japanese(target)
            return "翻訳したい文章を教えてください。"

        if self.matches_any(prompt, ["english", "英語", "translate to english", "to english", "英語に翻訳"]):
            target = prompt
            for prefix in ["translate", "translation", "to english", "英語に翻訳", "english"]:
                target = target.replace(prefix, "", 1).strip()
            if target:
                return self.translate_english(target)
            return "翻訳したい文章を教えてください。"

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

        if any(token in p for token in ["check inbox", "inbox", "new mail", "new email", "unread mail", "unread email"]):
            return self.check_inbox()

        if any(token in p for token in ["send email", "send mail", "email to"]):
            email_response = self.handle_send_email(prompt)
            if email_response:
                return email_response

        if self.matches_any(prompt, ["translate email", "translate message", "translate to english", "email translation", "message translation"]):
            return self.handle_translation_request(prompt)

        if any(token in p for token in ["recommend language", "language recommendation", "which language should", "suggest language", "best language"]):
            suggestion = self.recommend_language(prompt, context="meeting")
            return f"Recommended language: {suggestion['name']} ({suggestion['code']}). Reason: {suggestion['reason']}"

        if any(token in p for token in ["summarize meeting", "meeting summary", "summary of meeting", "summarize this meeting", "meeting notes"]):
            transcript = re.sub(r"^(summarize|summary)\s+(meeting|this meeting|the meeting|meeting notes)\s*[:\-]?\s*", "", prompt, flags=re.I)
            if not transcript or transcript == prompt:
                transcript = prompt.replace("summarize meeting", "", 1).replace("meeting summary", "", 1).replace("summary of meeting", "", 1).strip()
            if transcript:
                return self.summarize_meeting(transcript)
            return "Please paste the meeting transcript or notes to summarize."

        if any(token in p for token in ["summarize email", "summarize message", "summarize mail"]):
            return self.handle_summarize_email(prompt)

        if any(token in p for token in ["run command", "execute command", "shell command", "run shell", "execute shell"]):
            command = re.sub(r"^(run|execute)\s+(shell\s+|command\s+)", "", prompt, flags=re.I).strip()
            return self.run_shell_command(command)

        if any(token in p for token in ["open file", "read file", "show file"]):
            target = re.sub(r"^(open|read|show)\s+(file\s+)?", "", prompt, flags=re.I).strip()
            if target:
                return self.open_file_in_default_app(target)

        download_match = re.match(r"^(download|install|setup)\s+(.*)$", prompt, flags=re.I)
        if download_match:
            target = download_match.group(2).strip()
            if target and not target.lower().startswith("file "):
                return self.download_app(target)

        if any(token in p for token in ["search file", "find file", "locate file"]):
            query = re.sub(r"^(search|find|locate)\s+(file\s+)?", "", prompt, flags=re.I).strip()
            if query:
                matches = self.find_files(query, str(self.workspace_root))
                if matches:
                    return "Found files:\n- " + "\n- ".join(matches[:25])
                return f"No files found matching '{query}' in workspace."

        if any(token in p for token in ["list apps", "installed apps", "available apps"]):
            apps = self.list_installed_apps(40)
            if apps:
                return "Installed apps:\n- " + "\n- ".join(apps)
            return "I could not find installed apps yet."

        if any(token in p for token in ["list drives", "my drives", "available drives"]):
            if os.name == "nt":
                drives = []
                for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    path = f"{letter}:\\"
                    if os.path.exists(path):
                        drives.append(path)
                return "Drives:\n- " + "\n- ".join(drives)
            return "Drive listing is only available on Windows."

        if any(token in p for token in ["list folder", "show folder", "list directory", "open folder"]):
            target = re.sub(r"^(list|show|open)\s+(folder|directory)\s*", "", prompt, flags=re.I).strip()
            if not target:
                target = str(self.workspace_root)
            return "Contents:\n- " + "\n- ".join(self.list_directory_contents(target))

        if self._looks_like_app_request(prompt):
            app_name = self._normalize_app_name(prompt)
            if app_name and self.resolve_special_target(app_name) is not None:
                return self.open_special_target(app_name)
            if app_name:
                return self.launch_app(app_name)

        if re.search(r"(?i)\b(how are you|how's it going|how are things|what's up|yo|yoo)\b", prompt):
            return "I’m good — I’m here and ready to help with your PC, notes, meetings, and translations."

        if " and " in prompt.lower() and len(self.split_command_sequence(prompt)) > 1:
            return self.process_command_sequence(prompt)

        if self._fuzzy_matches(prompt, ["search", "find", "look", "what", "who", "when", "where", "why", "how", "検索", "調べて", "探して"]) and not self._fuzzy_matches(prompt, ["system", "status", "specs", "hardware"]) and not re.search(r"(?i)\b(how are you|how are things|what's up|how's it going)\b", prompt):
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

        if p.startswith("go to ") or p.startswith("open website ") or p.startswith("visit "):
            target = prompt.replace("go to", "", 1).replace("open website", "", 1).replace("visit", "", 1).strip()
            return self.open_website(target)

        if p.startswith("open ") or " open " in p:
            app_name = prompt.replace("open", "", 1).strip()
            if app_name:
                return self.launch_app(app_name)

        if p.startswith("launch ") or " launch " in p:
            app_name = prompt.replace("launch", "", 1).strip()
            if app_name:
                return self.launch_app(app_name)

        if any(keyword in p for keyword in ["検索", "検索して", "search", "find", "look up", "look for"]) :
            query = prompt
            for prefix in ["search for", "search", "find", "look up", "look for", "検索して", "検索", "探して", "調べて"]:
                query = query.replace(prefix, "", 1,).strip()
            if query:
                return self.search_web(query)

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

        advanced_response = self.ask_advanced_ai(prompt)
        if advanced_response:
            return advanced_response

        relevant_file = self._find_relevant_file(prompt)
        if relevant_file is not None:
            return (
                f"I found a likely relevant file: {relevant_file.relative_to(self.workspace_root)}. "
                "Ask me to summarize or explain it."
            )

        return (
            "I can help with your PC, open apps, browse the web, summarize files, remember notes, and translate when you ask for it. "
            "Translation only runs when you explicitly request it or activate live meeting mode."
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
    print("コマンド:")
    print("  !help                ヘルプを表示")
    print("  !memory              保存メモを表示")
    print("  !summarize <file>    ファイルを要約")
    print("  !explain <file>      ファイルを説明")
    print("  !exit                終了")


class AssistantDesktopUI:
    def __init__(self, assistant: LocalPrivateAssistant):
        self.assistant = assistant
        self.root = tk.Tk()
        self.root.title("RAY // Local Intelligence")
        self.root.geometry("1080x740")
        self.root.minsize(860, 600)
        self.root.configure(bg="#07111f")
        self.root.option_add("*Font", ("Segoe UI", 10))
        self._colors = {
            "background": "#07111f",
            "panel": "#0c1928",
            "inset": "#081421",
            "accent": "#31d7e8",
            "text": "#e5f3f7",
            "muted": "#87a6b5",
            "line": "#183448",
        }

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "Ray.TCombobox",
            fieldbackground="#0b1b2b",
            background="#10283a",
            foreground=self._colors["text"],
            arrowcolor=self._colors["accent"],
            bordercolor=self._colors["line"],
            padding=7,
        )

        header = tk.Frame(self.root, bg=self._colors["background"])
        header.pack(fill="x", padx=26, pady=(22, 18))
        brand = tk.Frame(header, bg=self._colors["background"])
        brand.pack(side="left")
        tk.Label(
            brand, text="RAY", fg=self._colors["accent"], bg=self._colors["background"],
            font=("Segoe UI", 26, "bold"),
        ).pack(anchor="w")
        tk.Label(
            brand, text="LOCAL INTELLIGENCE SYSTEM", fg=self._colors["muted"],
            bg=self._colors["background"], font=("Consolas", 9),
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(
            header, text="PRIVATE BY DESIGN  /  RUNNING ON THIS DEVICE",
            fg=self._colors["muted"], bg=self._colors["background"], font=("Consolas", 9),
        ).pack(side="right", anchor="s", pady=(0, 5))

        body = tk.Frame(self.root, bg=self._colors["background"])
        body.pack(fill="both", expand=True, padx=26, pady=(0, 24))

        left_frame = tk.Frame(body, bg=self._colors["panel"], highlightbackground=self._colors["line"], highlightthickness=1)
        left_frame.pack(fill="both", expand=True, side="left")
        right_frame = tk.Frame(body, width=270, bg=self._colors["panel"], highlightbackground=self._colors["line"], highlightthickness=1)
        right_frame.pack(fill="y", side="right", padx=(14, 0))
        right_frame.pack_propagate(False)

        self.chat_display = scrolledtext.ScrolledText(
            left_frame,
            bg=self._colors["inset"],
            fg=self._colors["text"],
            wrap="word",
            state="disabled",
            padx=20,
            pady=18,
            relief="flat",
            borderwidth=0,
            insertbackground=self._colors["accent"],
            font=("Segoe UI", 11),
        )
        self.chat_display.pack(fill="both", expand=True, padx=12, pady=12)
        self.chat_display.tag_configure("assistant", foreground=self._colors["accent"], font=("Segoe UI", 10, "bold"))
        self.chat_display.tag_configure("you", foreground="#f0b86e", font=("Segoe UI", 10, "bold"))
        self.chat_display.tag_configure("message", foreground=self._colors["text"], lmargin1=12, lmargin2=12, spacing3=12)

        input_row = tk.Frame(left_frame, bg=self._colors["panel"])
        input_row.pack(fill="x", padx=12, pady=(0, 12))
        self.command_input = tk.Entry(
            input_row, bg="#0b1b2b", fg=self._colors["text"], insertbackground=self._colors["accent"],
            relief="flat", font=("Segoe UI", 11),
        )
        self.command_input.pack(fill="x", side="left", expand=True, ipady=11, padx=(0, 9))
        self.command_input.bind("<Return>", lambda event: self.handle_send())
        self.send_button = tk.Button(
            input_row, text="TRANSMIT", command=self.handle_send, bg="#0d7483", fg="white",
            activebackground="#1597a6", activeforeground="white", relief="flat", width=13, pady=9,
            font=("Segoe UI", 9, "bold"),
        )
        self.send_button.pack(side="right")

        tk.Label(
            right_frame, text="SYSTEM STATUS", bg=self._colors["panel"], fg=self._colors["muted"],
            font=("Consolas", 9, "bold"), anchor="w",
        ).pack(fill="x", padx=16, pady=(18, 6))
        self.ollama_status = tk.Label(
            right_frame, text="Checking local Ollama...", bg=self._colors["panel"],
            fg=self._colors["accent"], font=("Segoe UI", 9), anchor="w", wraplength=228, justify="left",
        )
        self.ollama_status.pack(fill="x", padx=16)
        self.model_var = tk.StringVar(value="Loading local models...")
        self.model_picker = ttk.Combobox(
            right_frame, textvariable=self.model_var, state="readonly", style="Ray.TCombobox",
        )
        self.model_picker.pack(fill="x", padx=16, pady=(10, 6))
        self.model_picker.bind("<<ComboboxSelected>>", self.handle_model_selected)
        self.refresh_models_button = tk.Button(
            right_frame, text="REFRESH MODEL LIST", command=self.refresh_models,
            bg="#132a3c", fg=self._colors["accent"], activebackground="#1b3b50",
            activeforeground="white", relief="flat", pady=8, font=("Segoe UI", 8, "bold"),
        )
        self.refresh_models_button.pack(fill="x", padx=16, pady=(0, 14))

        divider = tk.Frame(right_frame, bg=self._colors["line"], height=1)
        divider.pack(fill="x", padx=16, pady=(0, 14))
        tk.Label(
            right_frame, text="QUICK ACTIONS", bg=self._colors["panel"], fg=self._colors["muted"],
            font=("Consolas", 9, "bold"), anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 8))
        button_frame = tk.Frame(right_frame, bg=self._colors["panel"])
        button_frame.pack(fill="x", padx=16)
        actions = [
            ("OPEN FILE", self.handle_open_file),
            ("OPEN FOLDER", self.handle_open_folder),
            ("SYSTEM INFO", self.handle_system_status),
            ("LOCAL MEMORY", self.handle_show_memory),
            ("CLEAR CONSOLE", self.handle_clear),
            ("VOICE COMMAND", self.handle_voice_command),
        ]
        for label, command in actions:
            tk.Button(
                button_frame, text=label, command=command, bg="#102235", fg=self._colors["text"],
                activebackground="#19384e", activeforeground=self._colors["accent"],
                relief="flat", anchor="w", padx=12, pady=9, font=("Segoe UI", 9, "bold"),
            ).pack(fill="x", pady=3)

        tk.Label(
            right_frame, text="VOICE BUTTON: SAY “HEY RAY” + A COMMAND", bg=self._colors["panel"],
            fg=self._colors["accent"], anchor="w", justify="left", wraplength=230,
            font=("Consolas", 8, "bold"),
        ).pack(fill="x", padx=16, pady=(18, 5))
        help_text = (
            "/ai explain a topic\n"
            "open firefox\n"
            "open file README.md\n"
            "summarize pew.py\n"
            "remember buy groceries"
        )
        tk.Label(
            right_frame, text=help_text, bg=self._colors["panel"], fg=self._colors["muted"],
            justify="left", wraplength=230, font=("Consolas", 9),
        ).pack(fill="x", padx=16, pady=(3, 0))

        self.append_message("assistant", "Ray online. Select an installed local model, then send a prompt or use a one-shot voice command.")
        self.refresh_models()

    def append_message(self, sender: str, text: str) -> None:
        self.chat_display.configure(state="normal")
        self.chat_display.insert(tk.END, f"{sender.upper()}  /  ", sender)
        self.chat_display.insert(tk.END, f"{text}\n\n", "message")
        self.chat_display.configure(state="disabled")
        self.chat_display.see(tk.END)

    def refresh_models(self) -> None:
        self.refresh_models_button.configure(state="disabled")
        self.ollama_status.configure(text="Scanning installed local models...", fg=self._colors["accent"])

        def load_models() -> None:
            try:
                models = self.assistant.list_ollama_models()
                result: tuple[List[str], Optional[str]] = (models, None)
            except RuntimeError as exc:
                result = ([], str(exc))
            self.root.after(0, lambda: self._finish_model_refresh(*result))

        threading.Thread(target=load_models, daemon=True).start()

    def _finish_model_refresh(self, models: List[str], error: Optional[str]) -> None:
        self.refresh_models_button.configure(state="normal")
        if error:
            self.model_picker.configure(values=())
            self.model_var.set("Ollama unavailable")
            self.assistant.selected_model = ""
            self.ollama_status.configure(text=error, fg="#f0b86e")
            return
        if not models:
            self.model_picker.configure(values=())
            self.model_var.set("No models installed")
            self.assistant.selected_model = ""
            self.ollama_status.configure(
                text="Ollama is connected. Install a model locally (for example: ollama pull qwen2.5:3b).",
                fg="#f0b86e",
            )
            return

        preferred = self.assistant.selected_model
        if preferred not in models:
            preferred = models[0]
        self.assistant.selected_model = preferred
        self.model_picker.configure(values=models)
        self.model_var.set(preferred)
        self.ollama_status.configure(
            text=f"OLLAMA ONLINE  /  {len(models)} local model{'s' if len(models) != 1 else ''} detected",
            fg=self._colors["accent"],
        )

    def handle_model_selected(self, _event: tk.Event) -> None:
        self.assistant.selected_model = self.model_var.get()
        self.ollama_status.configure(text=f"Active local model: {self.assistant.selected_model}", fg=self._colors["accent"])

    def handle_send(self) -> None:
        prompt = self.command_input.get().strip()
        if not prompt:
            return
        self.command_input.delete(0, tk.END)
        self.append_message("you", prompt)
        self.send_button.configure(state="disabled", text="PROCESSING")

        def process() -> None:
            try:
                response = self.assistant.handle_command(prompt)
            except Exception as exc:
                response = f"Ray could not complete that request: {exc}"
            self.root.after(0, lambda: self._finish_send(response))

        threading.Thread(target=process, daemon=True).start()

    def _finish_send(self, response: str) -> None:
        self.append_message("assistant", response)
        self.send_button.configure(state="normal", text="TRANSMIT")
        if self.assistant.voice_enabled:
            threading.Thread(target=self.assistant.speak, args=(response,), daemon=True).start()

    def handle_open_file(self) -> None:
        path = filedialog.askopenfilename(initialdir=self.assistant.workspace_root, title="Select file")
        if not path:
            return
        result = self.assistant.open_file_in_default_app(path)
        self.append_message("assistant", result)

    def handle_open_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.assistant.workspace_root, title="Select folder")
        if not folder:
            return
        items = self.assistant.list_directory_contents(folder)
        text = "Contents:\n- " + "\n- ".join(items) if items else f"No items found in {folder}"
        self.append_message("assistant", text)

    def handle_system_status(self) -> None:
        result = self.assistant.build_system_status()
        self.append_message("assistant", result)

    def handle_show_memory(self) -> None:
        result = self.assistant.show_memory()
        self.append_message("assistant", result)

    def handle_clear(self) -> None:
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", tk.END)
        self.chat_display.configure(state="disabled")

    def handle_voice_command(self) -> None:
        self.append_message("assistant", "Listening for a voice command...")

        def listen() -> None:
            if not self.assistant.voice_enabled and not self.assistant._setup_voice():
                result = "Offline voice packages are unavailable. Install SpeechRecognition, PocketSphinx, PyAudio, and pyttsx3."
            else:
                result = self.assistant.listen_once() or ""
            self.root.after(0, lambda: self._finish_voice_command(result))

        threading.Thread(target=listen, daemon=True).start()

    def _finish_voice_command(self, voice_text: str) -> None:
        if not voice_text:
            self.append_message("assistant", "No offline voice input recognized. Check your microphone and try again.")
            return
        self.command_input.delete(0, tk.END)
        self.command_input.insert(0, voice_text)
        self.handle_send()

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

    print("[offline-ai] Assistant ready. No cloud dependency required.")
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
