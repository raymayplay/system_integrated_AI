"""Ray's agent mode: Claude with tools for your PC, your browser and the web.

Handles anything the quick built-in commands can't: multi-step browser tasks
(booking, job applications, forms), web research, writing code, settings, and
handing coding tasks to Claude Code. Risky steps always ask you first.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .browser import Browser, BrowserError
from .system import IS_WINDOWS, System

MODEL = os.getenv("RAY_CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("RAY_EFFORT", "medium")
PROJECTS_DIR = Path.home() / "RayProjects"
MAX_STEPS = 40
YES_RE = re.compile(r"\b(yes|yeah|yep|yup|sure|ok|okay|go ahead|do it|confirm|confirmed|please do|correct|right|absolutely)\b", re.I)

SYSTEM_PROMPT = f"""You are Ray, a voice assistant that runs on the user's Windows PC and can act on it, like Alexa combined with an AI browser agent.

How you talk:
- Your final reply is spoken aloud. Keep it to one to three short, natural sentences. No markdown, lists, URLs or emoji.
- Don't narrate every step. Act, then report the outcome.

How you act:
- Simple PC actions (open or close an app or website, play or search YouTube, pause, next, volume, mute, open a folder): use quick_command.
- Windows settings: open_settings, set_dark_mode, set_brightness.
- Questions about facts, news, prices, weather or anything current: use web_search and answer directly, like Perplexity.
- Tasks on websites (booking, shopping, job applications, filling forms, checking accounts): use the browser tools. browser_open a site, read the numbered elements, then click and type by element number. Read again after the page changes. The browser keeps the user's logins.
- Writing code: write_file saves files (relative paths go into {PROJECTS_DIR}), then open_in_editor. For larger software projects, hand off with claude_code.
- Anything else on the PC: run_powershell (the user approves each command).

Safety rules (always follow these):
- Before anything that spends money, books or reserves, submits an application or form, sends a message, email or post, deletes files, or changes accounts, call ask_user with a clear summary of exactly what will happen and wait for a yes.
- Never invent personal details (name, phone, address, resume answers, payment info). Ask the user with ask_user, or use what they already told you.
- If a site needs a login, a password, a captcha or a payment card, ask the user to do that part themselves in the browser window, then continue.
- If something fails twice, stop and tell the user what went wrong instead of looping."""


def _tool(name: str, description: str, properties: Dict[str, Any] | None = None) -> Dict[str, Any]:
    properties = properties or {}
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False},
    }


_S = {"type": "string"}
_ELEMENT = {"type": "integer", "description": "The [number] of the element from the latest page read."}

TOOLS: List[Dict[str, Any]] = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5},
    _tool("quick_command", "Run one of Ray's built-in PC commands, written as the user would say it, e.g. 'open spotify', "
          "'close chrome', 'play lofi beats on youtube', 'search youtube for pasta recipes', 'volume up', 'pause', 'open downloads'.",
          {"command": _S}),
    _tool("open_settings", "Open a Windows Settings page, e.g. 'bluetooth', 'wifi', 'display', 'sound', 'windows update', 'privacy'. "
          "Use '' for the Settings home page.", {"page": _S}),
    _tool("set_dark_mode", "Switch Windows between dark mode (true) and light mode (false).", {"dark": {"type": "boolean"}}),
    _tool("set_brightness", "Set the screen brightness from 0 to 100 (laptop screens).", {"percent": {"type": "integer"}}),
    _tool("run_powershell", "Run a PowerShell command on the user's PC and return its output. The user must approve each command, "
          "so explain why in 'reason'.", {"command": _S, "reason": _S}),
    _tool("write_file", f"Create or overwrite a text file (code, notes, documents). Relative paths are saved in {PROJECTS_DIR}. "
          "Returns the full path.", {"path": _S, "content": _S}),
    _tool("open_in_editor", "Open a file or folder in VS Code (or the default app if VS Code is missing).", {"path": _S}),
    _tool("claude_code", "Hand a software task to Claude Code in a new terminal window, inside a project folder. Use for building "
          "or changing real codebases. 'folder' can be '' for a new folder in RayProjects.", {"task": _S, "folder": _S}),
    _tool("ask_user", "Ask the user a question out loud and wait for the spoken or typed answer. Required before purchases, bookings, "
          "submissions, sending messages, or deleting anything, and whenever you need information only the user has.",
          {"question": _S}),
    _tool("browser_open", "Open a URL in Ray's browser window and return the page text and its numbered interactive elements.", {"url": _S}),
    _tool("browser_read", "Read the current browser page again: text plus numbered interactive elements."),
    _tool("browser_click", "Click an element on the current page by its number.", {"element": _ELEMENT}),
    _tool("browser_type", "Type text into an input on the current page. Set submit to true to press Enter afterwards.",
          {"element": _ELEMENT, "text": _S, "submit": {"type": "boolean"}}),
    _tool("browser_select", "Choose an option in a dropdown (select element) by its visible text.", {"element": _ELEMENT, "option": _S}),
    _tool("browser_press", "Press a keyboard key in the browser, e.g. 'Enter', 'Escape', 'Tab', 'PageDown'.", {"key": _S}),
    _tool("browser_scroll", "Scroll the current page up or down to see more.", {"direction": {"type": "string", "enum": ["up", "down"]}}),
    _tool("browser_back", "Go back to the previous page."),
]

STEP_LABELS = {
    "web_search": "Searching the web",
    "quick_command": "Running a command",
    "open_settings": "Opening Settings",
    "set_dark_mode": "Changing the theme",
    "set_brightness": "Adjusting brightness",
    "run_powershell": "Running a command",
    "write_file": "Writing a file",
    "open_in_editor": "Opening the editor",
    "claude_code": "Handing off to Claude Code",
    "ask_user": "Waiting for you",
    "browser_open": "Opening the page",
    "browser_read": "Reading the page",
    "browser_click": "Clicking",
    "browser_type": "Typing",
    "browser_select": "Choosing an option",
    "browser_press": "Pressing a key",
    "browser_scroll": "Scrolling",
    "browser_back": "Going back",
}


def configured() -> bool:
    """True when the anthropic package is installed and credentials are set up."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("ANTHROPIC_AUTH_TOKEN")
        or (Path.home() / ".config" / "anthropic").exists()
    )


class Agent:
    def __init__(
        self,
        system: Optional[System] = None,
        quick_command: Callable[[str], str] = lambda command: "Quick commands are unavailable.",
        browser: Optional[Browser] = None,
        client: Any = None,
    ) -> None:
        self.system = system or System()
        self.quick_command = quick_command
        self.browser = browser or Browser()
        self._client = client
        self.messages: List[Dict[str, Any]] = []
        self._cancel = threading.Event()
        # Set by the UI. ask_user must block until the user answers.
        self.ask_user: Callable[[str], str] = lambda question: "(no user available to answer)"
        self.on_step: Callable[[str], None] = lambda text: None
        self.on_start: Callable[[], None] = lambda: None

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def cancel(self) -> None:
        self._cancel.set()

    # ------------------------------------------------------------------ loop
    def run(self, request: str) -> str:
        import anthropic

        self._cancel.clear()
        self.on_start()
        if len(self.messages) > 60:  # start a fresh conversation instead of growing forever
            self.messages = []
        self.messages.append({"role": "user", "content": request})

        for _ in range(MAX_STEPS):
            try:
                response = self.client.beta.messages.create(
                    model=MODEL,
                    max_tokens=16000,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=self.messages,
                    output_config={"effort": EFFORT},
                    cache_control={"type": "ephemeral"},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            except anthropic.AuthenticationError:
                self.messages = []
                return "My Claude API key isn't working. Please check ANTHROPIC_API_KEY."
            except anthropic.RateLimitError:
                self.messages = []
                return "I'm being rate limited by Claude right now. Try again in a minute."
            except anthropic.APIConnectionError:
                self.messages = []
                return "I can't reach Claude. Please check your internet connection."
            except anthropic.APIStatusError as exc:
                self.messages = []
                return f"Claude returned an error: {exc.status_code}."

            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                self.messages = []
                return "Sorry, I can't help with that one."
            if response.stop_reason == "pause_turn":
                continue
            tool_uses = [block for block in response.content if block.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                return _final_text(response.content) or "Done."

            results = []
            for block in tool_uses:
                if self._cancel.is_set():
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": "Cancelled by the user.", "is_error": True})
                    continue
                self.on_step(_step_label(block.name, block.input))
                try:
                    output = self._execute(block.name, block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
                except Exception as exc:
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {exc}", "is_error": True})
            self.messages.append({"role": "user", "content": results})
            if self._cancel.is_set():
                return "Okay, I stopped."

        return "That was taking too many steps, so I stopped. Tell me how you'd like to continue."

    # ----------------------------------------------------------------- tools
    def _confirm(self, question: str) -> bool:
        return bool(YES_RE.search(self.ask_user(question)))

    def _execute(self, name: str, args: Dict[str, Any]) -> str:
        b = self.browser
        if name == "quick_command":
            return self.quick_command(args["command"])
        if name == "open_settings":
            return "Opened Settings." if self.system.open_settings(args["page"]) else "Could not open Settings."
        if name == "set_dark_mode":
            ok = self.system.set_dark_mode(bool(args["dark"]))
            return ("Dark" if args["dark"] else "Light") + " mode is on." if ok else "Could not change the theme."
        if name == "set_brightness":
            return f"Brightness set to {args['percent']}%." if self.system.set_brightness(args["percent"]) else "This screen doesn't support brightness control."
        if name == "run_powershell":
            if not self._confirm(f"Can I run this command? {args['reason']}"):
                return "The user declined. Do not run it."
            return self.system.powershell(args["command"])
        if name == "write_file":
            return self._write_file(args["path"], args["content"])
        if name == "open_in_editor":
            return self._open_in_editor(args["path"])
        if name == "claude_code":
            return self._claude_code(args["task"], args["folder"])
        if name == "ask_user":
            return self.ask_user(args["question"])
        if name.startswith("browser_"):
            if not b.available():
                return "Browser control isn't installed. Tell the user to run: pip install playwright"
            try:
                if name == "browser_open":
                    return b.open(args["url"])
                if name == "browser_read":
                    return b.read()
                if name == "browser_click":
                    return b.click(args["element"])
                if name == "browser_type":
                    return b.type(args["element"], args["text"], args["submit"])
                if name == "browser_select":
                    return b.select(args["element"], args["option"])
                if name == "browser_press":
                    return b.press(args["key"])
                if name == "browser_scroll":
                    return b.scroll(args["direction"])
                if name == "browser_back":
                    return b.back()
            except BrowserError as exc:
                return f"Error: {exc}"
        return f"Error: unknown tool {name}"

    def _resolve(self, path: str) -> Path:
        p = Path(os.path.expandvars(path)).expanduser()
        return p if p.is_absolute() else PROJECTS_DIR / p

    def _write_file(self, path: str, content: str) -> str:
        target = self._resolve(path)
        inside = PROJECTS_DIR.resolve() in target.resolve().parents
        if not inside and not self._confirm(f"Can I save a file at {target}?"):
            return "The user declined. Save it inside RayProjects instead."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Saved {target}"

    def _open_in_editor(self, path: str) -> str:
        target = self._resolve(path)
        code = shutil.which("code")
        if code:
            subprocess.Popen([code, str(target)], shell=IS_WINDOWS)
            return f"Opened {target} in VS Code."
        return f"Opened {target}." if self.system._start(str(target)) else f"Could not open {target}."

    def _claude_code(self, task: str, folder: str) -> str:
        claude = shutil.which("claude")
        if not claude:
            return "Claude Code isn't installed. Tell the user to install it from claude.com/claude-code."
        target = self._resolve(folder) if folder else PROJECTS_DIR / re.sub(r"[^a-z0-9]+", "-", task.lower())[:40].strip("-")
        target.mkdir(parents=True, exist_ok=True)
        task_file = target / ".ray-task.txt"
        task_file.write_text(task, encoding="utf-8")
        if IS_WINDOWS:
            script = f"Set-Location '{target}'; claude (Get-Content -Raw '.ray-task.txt')"
            subprocess.Popen(["cmd", "/c", "start", "Claude Code", "powershell", "-NoExit", "-Command", script])
        else:
            subprocess.Popen(["x-terminal-emulator", "-e", "bash", "-lc", f"cd '{target}' && claude \"$(cat .ray-task.txt)\""])
        return f"Claude Code is now working on it in a new terminal, in {target}."


def _final_text(content) -> str:
    return " ".join(block.text for block in content if getattr(block, "type", "") == "text").strip()


def _step_label(name: str, args: Dict[str, Any]) -> str:
    label = STEP_LABELS.get(name, "Working")
    detail = args.get("url") or args.get("command") or args.get("page") or args.get("question") or ""
    if name == "browser_open":
        detail = re.sub(r"^https?://(www\.)?", "", detail).split("/")[0]
    if name in ("ask_user", "run_powershell"):
        detail = ""
    return f"{label} {detail}".strip() + "…"
