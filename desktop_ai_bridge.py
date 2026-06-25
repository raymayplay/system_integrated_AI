import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def parse_intent(text: str) -> dict:
    lowered = text.lower().strip()
    if not lowered:
        return {"action": "chat"}
    if any(word in lowered for word in ["open firefox", "open chrome", "open edge", "open notepad", "open settings", "open gmail", "open youtube"]):
        return {"action": "launch", "target": lowered}
    if any(word in lowered for word in ["search", "youtube", "google"]):
        return {"action": "search", "query": lowered}
    if any(word in lowered for word in ["system", "pc", "folder", "files"]):
        return {"action": "system", "query": lowered}
    return {"action": "chat", "query": lowered}


def handle_command(text: str) -> str:
    intent = parse_intent(text)
    if intent["action"] == "launch":
        target = intent["target"]
        if "firefox" in target:
            subprocess.Popen(["firefox.exe"])
            return "Opened Firefox."
        if "youtube" in target:
            subprocess.Popen(["firefox.exe", "https://www.youtube.com"])
            return "Opened YouTube in Firefox."
        if "gmail" in target:
            subprocess.Popen(["firefox.exe", "https://mail.google.com"])
            return "Opened Gmail in Firefox."
        if "settings" in target:
            os.startfile("ms-settings:")
            return "Opened Windows Settings."
        return f"I can open that on your PC: {text}"
    if intent["action"] == "search":
        if "youtube" in intent["query"]:
            subprocess.Popen(["firefox.exe", "https://www.youtube.com"])
            return "Opened YouTube."
        return "I can open a browser search for that request."
    if intent["action"] == "system":
        return "I can inspect your desktop, folders, and app state locally."
    return f"I understand your request: {text}. I can help with desktop actions and local tasks."


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print(handle_command(" ".join(sys.argv[1:])))
    else:
        print(json.dumps({"status": "ready"}))
