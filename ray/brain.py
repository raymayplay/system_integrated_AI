"""Conversation with a local Ollama model."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Dict, List

SYSTEM_PROMPT = """You are Ray, a friendly voice assistant running on the user's Windows PC, similar to Alexa or Siri.
Your replies are spoken aloud, so keep them short: one to three natural sentences, no markdown, no lists, no emoji.

If the user wants something done on the computer that you were not given a direct command for, reply with exactly one line:
ACTION: <command>
where <command> is one of these forms:
  open <app or website>
  close <app>
  play <video or song> on youtube
  search youtube for <query>
  search <query>
  volume up | volume down | mute | pause | next
Example: "put on some relaxing piano" -> ACTION: play relaxing piano music on youtube
Otherwise, just answer the question."""


class Brain:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen3:8b")
        self.history: List[Dict[str, str]] = []

    def list_models(self) -> List[str]:
        with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
        return [m["name"] for m in data.get("models", []) if isinstance(m, dict) and isinstance(m.get("name"), str)]

    def ask(self, prompt: str) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *self.history[-10:], {"role": "user", "content": prompt}]
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.4},
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return f"The model {self.model} isn't installed. Run: ollama pull {self.model}"
            return f"Ollama returned an error: {exc.code}."
        except (OSError, ValueError):
            return "I can't reach my local brain right now. Please start Ollama and try again."

        reply = clean_reply(str(data.get("message", {}).get("content", "")))
        if not reply:
            return "Sorry, I didn't catch that."
        self.history += [{"role": "user", "content": prompt}, {"role": "assistant", "content": reply}]
        return reply


def clean_reply(text: str) -> str:
    text = re.sub(r"(?s)<think>.*?</think>", "", text)
    text = re.sub(r"[*_`#]+", "", text)
    return text.strip()


def extract_action(reply: str) -> str | None:
    match = re.search(r"(?im)^\s*ACTION:\s*(.+?)\s*$", reply)
    return match.group(1) if match else None
