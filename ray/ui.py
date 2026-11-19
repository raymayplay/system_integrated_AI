"""Ray's futuristic, Siri-style interface (pure tkinter, no extra packages)."""

from __future__ import annotations

import math
import os
import queue
import random
import threading
import time
import tkinter as tk
from typing import Callable, List, Optional

from .commands import CommandEngine, Reply
from .voice import Listener, Speaker
from .youtube import Video

FONT = "Segoe UI" if os.name == "nt" else "Helvetica"
BG_TOP, BG_BOTTOM = "#0b1033", "#020309"
TEXT, MUTED, DIM = "#f4f7ff", "#8a94c0", "#3a4370"
PILL, PILL_EDGE = "#10153a", "#2a3270"
GREEN, RED, CYAN = "#3dffa8", "#ff5d73", "#38f0ff"

STATE_COLORS = {
    "idle": ("#3b5bff", "#8a4dff", "#22c3ff"),
    "listening": ("#38f0ff", "#2f8cff", "#5bffd0"),
    "thinking": ("#a259ff", "#ff4fd8", "#5b6cff"),
    "speaking": ("#ff4fd8", "#38f0ff", "#a259ff"),
}
STATE_ENERGY = {"idle": 0.12, "listening": 0.55, "thinking": 0.32, "speaking": 0.6}
STATE_CAPTION = {
    "idle": "Say “Hey Ray” or type below",
    "listening": "Listening…",
    "thinking": "Thinking",
    "speaking": "",
}
# (frequency, phase speed, amplitude share, colour slot)
WAVES = [(1.6, 0.11, 1.0, 0), (2.3, -0.08, 0.75, 1), (1.1, 0.06, 0.6, 2), (2.9, 0.14, 0.4, 0)]
GLOW = [(11, 0.86), (6, 0.62), (2, 0.0)]  # (line width, how much it fades into the background)
POINTS = 72


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def mix(a: str, b: str, t: float) -> str:
    """Blend colour a toward colour b by t (0 = a, 1 = b)."""
    (r1, g1, b1), (r2, g2, b2) = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % (round(r1 + (r2 - r1) * t), round(g1 + (g2 - g1) * t), round(b1 + (b2 - b1) * t))


def _enable_crisp_windows_rendering() -> None:
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except Exception:
            pass


def _dark_title_bar(root: tk.Tk) -> None:
    if os.name == "nt":
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(root.winfo_id())  # type: ignore[attr-defined]
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), 4)  # type: ignore[attr-defined]
        except Exception:
            pass


class RayApp:
    def __init__(self, engine: Optional[CommandEngine] = None) -> None:
        _enable_crisp_windows_rendering()
        self.root = tk.Tk()
        self.root.title("Ray")
        self.root.geometry("520x820")
        self.root.minsize(420, 660)
        self.root.configure(bg=BG_BOTTOM)
        _dark_title_bar(self.root)

        self.engine = engine or CommandEngine()
        self._events: "queue.Queue[tuple[Callable, tuple]]" = queue.Queue()
        self.state = "idle"
        self.energy = 0.1
        self.target_energy = 0.1
        self.colors = list(STATE_COLORS["idle"])
        self.phase = 0.0
        self.speak_replies = True
        self._follow_up = False
        self._busy = False  # a command or agent task is running
        self._step = ""  # what the agent is doing right now
        self._question: Optional[tuple[threading.Event, dict]] = None  # agent waiting for an answer
        self._videos: List[Video] = []
        self._playing: Optional[int] = None
        self._width = self._height = 0
        self.wave_y = 0.0
        self.bg_at_wave = BG_BOTTOM

        self.speaker = Speaker(on_start=lambda: self.post(self.set_state, "speaking"), on_done=lambda: self.post(self._speech_done))
        self.listener = Listener(
            on_command=lambda text: self.post(self.submit, text, True),
            on_state=lambda state: self.post(self.set_state, state),
            on_error=lambda message: self.post(self._voice_error, message),
            is_speaking=lambda: self.speaker.busy,
        )

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0, bg=BG_BOTTOM)
        self.canvas.pack(fill="both", expand=True)
        self._build()
        self.canvas.bind("<Configure>", self._on_resize)
        self.root.bind("<Control-space>", lambda _e: self.push_to_talk())
        self.root.bind("<F2>", lambda _e: self.push_to_talk())
        self.root.bind("<Escape>", lambda _e: self.stop())

        self.listener.start()
        agent = self.engine.agent
        if agent is not None:
            agent.ask_user = self.ask_user_blocking
            agent.on_step = lambda text: self.post(self._set_step, text)
            agent.on_start = lambda: self.post(self._agent_started)
        self.root.after(200, self._load_models)
        self.root.after(16, self._tick)
        self.post(self._greet)

    # --------------------------------------------------------------- plumbing
    def post(self, fn: Callable, *args) -> None:
        """Run fn on the UI thread (safe to call from any thread)."""
        self._events.put((fn, args))

    def run(self) -> None:
        self.root.mainloop()

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        c = self.canvas
        self.orb = [c.create_oval(0, 0, 0, 0, outline="", fill=BG_BOTTOM, tags="orb") for _ in range(16)]
        self.lines = [
            [[c.create_line(0, 0, 0, 0, width=w, capstyle="round", smooth=True, splinesteps=4) for w, _ in GLOW] for _ in (1, -1)]
            for _ in WAVES
        ]
        self.center_line = c.create_line(0, 0, 0, 0, fill="#c9d4ff", width=1)

        self.title = c.create_text(0, 0, text="R  A  Y", fill=TEXT, font=(FONT, 13, "bold"), anchor="w")
        self.model_label = c.create_text(0, 0, text="● connecting…", fill=MUTED, font=(FONT, 9), anchor="w")
        self.wake_toggle = c.create_text(0, 0, text="", font=(FONT, 9, "bold"), anchor="e")
        self.sound_toggle = c.create_text(0, 0, text="", fill=MUTED, font=(FONT, 9, "bold"), anchor="e")
        for item, action in ((self.wake_toggle, self.toggle_wake), (self.sound_toggle, self.toggle_sound), (self.model_label, self._model_menu)):
            c.tag_bind(item, "<Button-1>", lambda _e, a=action: a())
            c.tag_bind(item, "<Enter>", lambda _e: c.config(cursor="hand2"))
            c.tag_bind(item, "<Leave>", lambda _e: c.config(cursor=""))
        self._refresh_toggles()

        self.caption = c.create_text(0, 0, text="", fill=MUTED, font=(FONT, 11), justify="center")
        self.you_text = c.create_text(0, 0, text="", fill=MUTED, font=(FONT, 12, "italic"), justify="center", anchor="n")
        self.reply_text = c.create_text(0, 0, text="", fill=TEXT, font=(FONT, 17), justify="center", anchor="n")

        self.pill = c.create_polygon(0, 0, 0, 0, smooth=True, fill=PILL, outline=PILL_EDGE, width=1)
        self.entry = tk.Entry(
            c, bd=0, relief="flat", bg=PILL, fg=TEXT, insertbackground=CYAN, font=(FONT, 12),
            highlightthickness=0, disabledbackground=PILL,
        )
        self.entry_window = c.create_window(0, 0, window=self.entry, anchor="w")
        self.entry.bind("<Return>", lambda _e: self._submit_entry())
        self.entry.bind("<FocusIn>", lambda _e: self._placeholder(False))
        self.entry.bind("<FocusOut>", lambda _e: self._placeholder(True))
        self._placeholder(True)

        self.mic = c.create_oval(0, 0, 0, 0, fill="#1b2360", outline="", tags="mic")
        self.mic_glyph = [
            c.create_line(0, 0, 0, 0, fill=TEXT, width=7, capstyle="round", tags="mic"),  # capsule
            c.create_arc(0, 0, 0, 0, start=180, extent=180, style="arc", outline=TEXT, width=2, tags="mic"),
            c.create_line(0, 0, 0, 0, fill=TEXT, width=2, tags="mic"),  # stem
        ]
        c.tag_bind("mic", "<Button-1>", lambda _e: self.push_to_talk())
        c.tag_bind("mic", "<Enter>", lambda _e: c.config(cursor="hand2"))
        c.tag_bind("mic", "<Leave>", lambda _e: c.config(cursor=""))
        c.tag_bind("orb", "<Button-1>", lambda _e: self.push_to_talk())

        self.hint = c.create_text(0, 0, text="Enter to send  ·  Ctrl+Space to talk  ·  Esc to stop", fill=DIM, font=(FONT, 9))

    def _placeholder(self, show: bool) -> None:
        if show and not self.entry.get():
            self.entry.insert(0, "Ask Ray anything…")
            self.entry.config(fg=MUTED)
            self._has_placeholder = True
        elif not show and getattr(self, "_has_placeholder", False):
            self.entry.delete(0, "end")
            self.entry.config(fg=TEXT)
            self._has_placeholder = False

    # ----------------------------------------------------------------- layout
    def _on_resize(self, event: tk.Event) -> None:
        self._width, self._height = event.width, event.height
        w, h, c = event.width, event.height, self.canvas
        c.delete("bg")
        steps = 64
        for i in range(steps):
            y0, y1 = h * i / steps, h * (i + 1) / steps + 1
            c.create_rectangle(0, y0, w, y1, fill=mix(BG_TOP, BG_BOTTOM, i / (steps - 1)), outline="", tags="bg")
        c.tag_lower("bg")

        self.wave_y = h * 0.29
        self.bg_at_wave = mix(BG_TOP, BG_BOTTOM, 0.29)
        c.coords(self.title, 26, 34)
        c.coords(self.model_label, 28, 56)
        c.coords(self.wake_toggle, w - 26, 34)
        c.coords(self.sound_toggle, w - 26, 56)
        c.coords(self.caption, w / 2, self.wave_y + h * 0.15)
        for item in (self.you_text, self.reply_text):
            c.itemconfig(item, width=w - 70)

        y, r = h - 74, 25
        x0, x1 = 22, w - 22
        c.coords(self.pill, *self._rounded(x0, y - r, x1, y + r, r))
        c.coords(self.entry_window, x0 + 22, y)
        c.itemconfig(self.entry_window, width=x1 - x0 - 90, height=30)
        mx, mr = x1 - 30, 19
        c.coords(self.mic, mx - mr, y - mr, mx + mr, y + mr)
        c.coords(self.mic_glyph[0], mx, y - 8, mx, y - 1)
        c.coords(self.mic_glyph[1], mx - 8, y - 11, mx + 8, y + 5)
        c.coords(self.mic_glyph[2], mx, y + 5, mx, y + 10)
        c.coords(self.hint, w / 2, h - 28)
        self._layout_text()

    def _layout_text(self) -> None:
        if not self._width:
            return
        c = self.canvas
        top = self.wave_y + self._height * 0.15 + 30
        c.coords(self.you_text, self._width / 2, top)
        box = c.bbox(self.you_text)
        reply_top = (box[3] + 14) if box and c.itemcget(self.you_text, "text") else top
        c.coords(self.reply_text, self._width / 2, reply_top)
        box = c.bbox(self.reply_text)
        self._draw_videos((box[3] + 20) if box and c.itemcget(self.reply_text, "text") else reply_top)

    @staticmethod
    def _rounded(x0: float, y0: float, x1: float, y1: float, r: float) -> list[float]:
        return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]

    def _draw_videos(self, top: float) -> None:
        c = self.canvas
        c.delete("video")
        limit = self._height - 120
        for i, video in enumerate(self._videos):
            y0 = top + i * 50
            if y0 + 44 > limit:
                break
            tag = f"video{i}"
            playing = i == self._playing
            fill = "#1a2156" if playing else "#0f143a"
            c.create_polygon(*self._rounded(30, y0, self._width - 30, y0 + 44, 14), smooth=True, fill=fill,
                             outline=CYAN if playing else PILL_EDGE, tags=("video", tag, f"{tag}bg"))
            c.create_oval(42, y0 + 10, 66, y0 + 34, fill=CYAN if playing else "#26306e", outline="", tags=("video", tag))
            c.create_text(54, y0 + 22, text="▶" if playing else str(i + 1), fill=BG_BOTTOM if playing else TEXT,
                          font=(FONT, 9, "bold"), tags=("video", tag))
            max_chars = max(20, int((self._width - 130) / 7.5))
            title = video.title if len(video.title) <= max_chars else video.title[: max_chars - 1] + "…"
            c.create_text(78, y0 + 15, text=title, fill=TEXT, font=(FONT, 10, "bold"), anchor="w", tags=("video", tag))
            meta = "  ·  ".join(part for part in (video.channel, video.duration) if part)
            c.create_text(78, y0 + 31, text=meta, fill=MUTED, font=(FONT, 9), anchor="w", tags=("video", tag))
            c.tag_bind(tag, "<Button-1>", lambda _e, n=i: self.submit(f"play number {n + 1}"))
            c.tag_bind(tag, "<Enter>", lambda _e, t=tag: (c.config(cursor="hand2"), c.itemconfig(f"{t}bg", fill="#1d2766")))
            c.tag_bind(tag, "<Leave>", lambda _e, t=tag, f=fill: (c.config(cursor=""), c.itemconfig(f"{t}bg", fill=f)))

    # -------------------------------------------------------------- animation
    def _tick(self) -> None:
        while True:
            try:
                fn, args = self._events.get_nowait()
            except queue.Empty:
                break
            fn(*args)
        if self._width:
            self._animate()
        self.root.after(16, self._tick)

    def _animate(self) -> None:
        c, w = self.canvas, self._width
        t = time.monotonic()
        base = STATE_ENERGY[self.state]
        if self.state == "idle":
            self.target_energy = base + 0.05 * math.sin(t * 1.6)
        elif self.state in ("speaking", "listening") and random.random() < 0.12:
            self.target_energy = base * random.uniform(0.45, 1.45)
        elif self.state == "thinking":
            self.target_energy = base + 0.12 * math.sin(t * 5)
        self.energy += (self.target_energy - self.energy) * 0.12
        self.phase += 0.9 if self.state == "thinking" else 0.45

        targets = STATE_COLORS[self.state]
        if self.state == "thinking":  # colours slowly swirl while thinking
            shift = int(t * 2) % 3
            targets = targets[shift:] + targets[:shift]
        self.colors = [mix(cur, tgt, 0.08) for cur, tgt in zip(self.colors, targets)]

        # soft glowing orb behind the waves
        cx, cy = w / 2, self.wave_y
        radius = min(w, self._height) * (0.20 + self.energy * 0.16)
        n = len(self.orb)
        for k, item in enumerate(self.orb):
            share = 1 - k / n
            rr = radius * (0.35 + 0.95 * share)
            c.coords(item, cx - rr, cy - rr, cx + rr, cy + rr)
            c.itemconfig(item, fill=mix(self.bg_at_wave, self.colors[0], 0.34 * (k / n) ** 1.8))

        # Siri-style waves: attenuated sine ribbons, mirrored around the centre line
        left, right = 30, w - 30
        height = self._height * 0.12 * (0.25 + self.energy * 1.6)
        for (freq, speed, share, slot), mirrored in zip(WAVES, self.lines):
            color = self.colors[slot]
            for sign, layers in zip((1, -1), mirrored):
                points: list[float] = []
                for i in range(POINTS):
                    xn = -2 + 4 * i / (POINTS - 1)
                    attenuation = (4 / (4 + xn ** 4)) ** 4
                    y = sign * height * share * attenuation * math.sin(freq * xn * math.pi - self.phase * speed * 3)
                    points += [left + (right - left) * i / (POINTS - 1), cy + y]
                for item, (_width, fade) in zip(layers, GLOW):
                    c.coords(item, *points)
                    c.itemconfig(item, fill=mix(color, self.bg_at_wave, fade))
        c.coords(self.center_line, left + 40, cy, right - 40, cy)
        c.itemconfig(self.center_line, fill=mix("#c9d4ff", self.bg_at_wave, 0.55))

        caption = STATE_CAPTION[self.state]
        if self.state == "thinking":
            caption = (self._step.rstrip("\u2026") if self._step else caption) + "." * (1 + int(t * 3) % 3)
        if self.state == "idle" and not self.listener.available:
            caption = "Type below to talk to Ray"
        if self._question is not None and self.state in ("idle", "listening"):
            caption = "Waiting for your answer \u00b7 say or type it"
        c.itemconfig(self.caption, text=caption)
        c.itemconfig(self.mic, fill=mix("#1b2360", CYAN, 0.55 + 0.3 * math.sin(t * 6)) if self.state == "listening" else "#1b2360")

    # ----------------------------------------------------------------- states
    def set_state(self, state: str) -> None:
        self.state = state
        if state == "listening":
            self.speaker.stop()

    def _speech_done(self) -> None:
        if self.state == "speaking":
            self.set_state("thinking" if self._busy else "idle")
        if self._follow_up:
            self._follow_up = False
            self.listener.listen_now()

    def _voice_error(self, message: str) -> None:
        self.set_state("idle")
        self.canvas.itemconfig(self.caption, text=message)
        self._show(None, message)

    def _refresh_toggles(self) -> None:
        if not self.listener.available:
            self.canvas.itemconfig(self.wake_toggle, text="● VOICE OFF", fill=DIM)
        elif self.listener.wake_enabled:
            self.canvas.itemconfig(self.wake_toggle, text="● HEY RAY: ON", fill=GREEN)
        else:
            self.canvas.itemconfig(self.wake_toggle, text="● HEY RAY: OFF", fill=MUTED)
        if not self.speaker.available:
            self.canvas.itemconfig(self.sound_toggle, text="SPEECH OFF", fill=DIM)
        else:
            self.canvas.itemconfig(self.sound_toggle, text="VOICE REPLIES: " + ("ON" if self.speak_replies else "OFF"))

    def toggle_wake(self) -> None:
        if not self.listener.available:
            self._show(None, self.listener.problem or "Voice is unavailable.")
            return
        self.listener.wake_enabled = not self.listener.wake_enabled
        self._refresh_toggles()

    def toggle_sound(self) -> None:
        self.speak_replies = not self.speak_replies
        if not self.speak_replies:
            self.speaker.stop()
        self._refresh_toggles()

    # ---------------------------------------------------------------- actions
    def _greet(self) -> None:
        hour = time.localtime().tm_hour
        part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        self._show(None, f"Good {part}. How can I help?")

    def _show(self, you: Optional[str], reply: str) -> None:
        if len(reply) > 700:
            reply = reply[:700].rsplit(" ", 1)[0] + "…"
        size = 17 if len(reply) < 90 else 14 if len(reply) < 220 else 12
        self.canvas.itemconfig(self.you_text, text=f"“{you}”" if you else "")
        self.canvas.itemconfig(self.reply_text, text=reply, font=(FONT, size))
        self._layout_text()

    def _submit_entry(self) -> None:
        if getattr(self, "_has_placeholder", False):
            return
        text = self.entry.get().strip()
        self.entry.delete(0, "end")
        if text:
            self.submit(text)

    def submit(self, text: str, from_voice: bool = False) -> None:
        if self._question is not None:  # this is the answer to the agent's question
            event, box = self._question
            self._question = None
            box["answer"] = text
            event.set()
            self.speaker.stop()
            self._show(text, "")
            self.set_state("thinking")
            return
        if self._busy:
            self._show(None, "I'm still working on the last task. Press Esc to stop it.")
            return
        self.speaker.stop()
        self._show(text, "")
        self._busy = True
        self._step = ""
        self.set_state("thinking")

        def work() -> None:
            try:
                reply = self.engine.handle(text)
            except Exception as exc:  # never let one bad command kill the app
                reply = Reply(f"Something went wrong: {exc}")
            self.post(self._finish, text, reply, from_voice)

        threading.Thread(target=work, daemon=True).start()

    def _finish(self, text: str, reply: Reply, from_voice: bool) -> None:
        self._busy = False
        self._step = ""
        if reply.videos:
            self._videos = reply.videos
            self._playing = self.engine.video_index
        # With video cards on screen, the first line is enough; the cards show the list.
        self._show(text, reply.text.splitlines()[0].rstrip(":") + "." if reply.videos else reply.text)
        spoken = reply.spoken.strip()
        if reply.stop_speaking or not spoken or not (self.speak_replies and self.speaker.available):
            self.speaker.stop()
            self.set_state("idle")
            return
        self._follow_up = from_voice and spoken.endswith("?") and self.listener.available
        self.speaker.say(spoken)

    def push_to_talk(self) -> None:
        if not self.listener.available:
            self._show(None, self.listener.problem or "Voice is unavailable.")
            return
        self.speaker.stop()
        self.listener.listen_now()

    def stop(self) -> None:
        self.speaker.stop()
        self._follow_up = False
        if self.engine.agent is not None and self._busy:
            self.engine.agent.cancel()
            self._step = "Stopping"
        if self._question is not None:
            event, box = self._question
            self._question = None
            box["answer"] = "no, stop"
            event.set()
        if self._busy:
            return
        self.set_state("idle")

    # ------------------------------------------------------------------ agent
    def _agent_started(self) -> None:
        if self.speak_replies and self.speaker.available:
            self.speaker.say("On it.")

    def _set_step(self, text: str) -> None:
        self._step = text

    def ask_user_blocking(self, question: str) -> str:
        """Called from the agent's thread: ask out loud, wait for the answer."""
        event, box = threading.Event(), {}
        self.post(self._begin_question, question, event, box)
        if not event.wait(timeout=600):
            self.post(self._end_question_timeout)
            return "(the user did not answer)"
        return box.get("answer", "")

    def _begin_question(self, question: str, event: threading.Event, box: dict) -> None:
        self._question = (event, box)
        self._step = "Waiting for your answer"
        self._show(None, question)
        if self.speak_replies and self.speaker.available:
            self._follow_up = self.listener.available
            self.speaker.say(question)
        else:
            self.set_state("idle")
        self.entry.focus_set()

    def _end_question_timeout(self) -> None:
        self._question = None

    # ----------------------------------------------------------------- models
    def _load_models(self) -> None:
        def work() -> None:
            try:
                models = self.engine.brain.list_models()
            except Exception:
                models = None
            self.post(self._models_loaded, models)

        threading.Thread(target=work, daemon=True).start()

    def _models_loaded(self, models: Optional[List[str]]) -> None:
        if self.engine.agent is not None:
            self._models = models or []
            self.canvas.itemconfig(self.model_label, text="\u25cf Claude agent ready", fill=GREEN)
            return
        self._models = models or []
        brain = self.engine.brain
        if models is None:
            self.canvas.itemconfig(self.model_label, text="● Ollama offline · click to retry", fill=RED)
            return
        if models and brain.model not in models:
            brain.model = models[0]
        label = brain.model if models else "no models installed"
        self.canvas.itemconfig(self.model_label, text=f"● {label}  ▾", fill=GREEN if models else RED)

    def _model_menu(self) -> None:
        if self.engine.agent is not None:
            return
        if not getattr(self, "_models", None):
            self.canvas.itemconfig(self.model_label, text="● connecting…", fill=MUTED)
            self._load_models()
            return
        menu = tk.Menu(self.root, tearoff=0, bg=PILL, fg=TEXT, activebackground="#26306e", activeforeground=TEXT, bd=0)
        for name in self._models:
            menu.add_command(label=("✓ " if name == self.engine.brain.model else "   ") + name,
                             command=lambda n=name: self._pick_model(n))
        menu.tk_popup(self.root.winfo_pointerx(), self.root.winfo_pointery())

    def _pick_model(self, name: str) -> None:
        self.engine.brain.model = name
        self._models_loaded(self._models)
