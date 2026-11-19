"""Turns what you say into actions.

Fast, rule-based handling for everyday commands (apps, YouTube, media,
volume, settings...). Bigger tasks (booking, applying, writing code, research)
go to the Claude agent, and the local Ollama model is the offline fallback.
"""

from __future__ import annotations

import datetime as dt
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import quote, quote_plus

from . import youtube
from .brain import Brain, extract_action
from .system import APPS, FOLDERS, System
from .youtube import Video

WAKE_RE = re.compile(
    r"\b(?:(?:hey|hi|hello|okay|ok|yo|a)[\s,]+(?:ray|rey|rae|wray|re|rate|bray|gray|grey|pray|reh)|ray|rey|rae)\b[\s,.!?]*",
    re.I,
)
_FILLER_START = re.compile(
    r"^(?:please|can you|could you|would you|will you|can u|i want you to|i want to|i'd like to|"
    r"i would like to|let's|lets|just|now|go ahead and|kindly)\s+",
    re.I,
)
_FILLER_END = re.compile(r"\s+(?:please|for me|now|right now|thanks|thank you)$", re.I)
_SPLIT_RE = re.compile(
    r"\s*;\s*|\s+(?:and then|then|and also|and)\s+(?=(?:open|close|play|search|launch|start|pause|resume|"
    r"mute|unmute|volume|turn|go to|google|look up|lock|remember|quit)\b)",
    re.I,
)
ORDINALS = {
    "first": 0, "1st": 0, "one": 0, "1": 0, "top": 0,
    "second": 1, "2nd": 1, "two": 1, "2": 1,
    "third": 2, "3rd": 2, "three": 2, "3": 2,
    "fourth": 3, "4th": 3, "four": 3, "4": 3,
    "fifth": 4, "5th": 4, "five": 4, "5": 4,
    "last": -1,
}
_ORD = "|".join(sorted(map(re.escape, ORDINALS), key=len, reverse=True))


@dataclass
class Reply:
    text: str
    speech: Optional[str] = None  # what to say aloud, if shorter than the display text
    videos: List[Video] = field(default_factory=list)
    stop_speaking: bool = False

    @property
    def spoken(self) -> str:
        return self.speech if self.speech is not None else self.text


AGENT_RE = re.compile(
    r"\b(book|booking|reserve|buy|order|purchase|checkout|apply|application|job|jobs|fill|form|sign up|register|"
    r"write|code|program|script|website|app for|build|create|make me|draft|compose|email|mail|message|send|reply|"
    r"compare|research|best|cheapest|summari[sz]e|explain|plan|schedule|install|download|fix|debug|claude|"
    r"flight|flights|hotel|ticket|tickets|restaurant|news|weather|price|how much|who is|what is|what are|why|how do|how to)\b",
    re.I,
)
_QUICK_RE = re.compile(r"^(play|pause|resume|next|skip|previous|volume|mute|unmute|open|launch|start|close|quit|lock|"
                       r"turn|set|brightness|take|search youtube|youtube|remember)\b")


def find_wake_word(text: str, strict: bool = False) -> tuple[bool, str]:
    """Return (heard_wake_word, the command spoken after it).

    strict=True (used for the always-on microphone) only accepts the wake word
    at the start of what was heard, so normal conversation in the room doesn't
    trigger Ray.
    """
    match = WAKE_RE.search(text)
    if not match or (strict and len(text[: match.start()].split()) > 1):
        return False, text.strip()
    return True, text[match.end():].strip(" ,.!?")


def clean(text: str) -> str:
    _, text = find_wake_word(text) if WAKE_RE.match(text.strip()) else (False, text)
    text = re.sub(r"\s+", " ", text.lower()).strip(" .!?,")
    text = text.replace("you tube", "youtube")
    previous = None
    while previous != text:
        previous = text
        text = _FILLER_START.sub("", text)
        text = _FILLER_END.sub("", text)
    return text.strip(" .!?,")


class CommandEngine:
    def __init__(
        self,
        system: Optional[System] = None,
        brain: Optional[Brain] = None,
        notes_path: Optional[Path] = None,
        search_youtube: Callable[[str], List[Video]] = youtube.search,
        agent="auto",
    ) -> None:
        self.system = system or System()
        self.brain = brain or Brain()
        self.notes_path = notes_path or Path.home() / ".ray" / "notes.txt"
        self.search_youtube = search_youtube
        self.videos: List[Video] = []  # last YouTube results, for "play that video"
        self.video_index: Optional[int] = None  # which result is playing
        self.pending: Optional[tuple[str, Callable[[], Reply]]] = None  # action waiting for "yes"
        if agent == "auto":
            from . import agent as agent_module

            agent = agent_module.Agent(self.system, self._quick_command) if agent_module.configured() else None
        self.agent = agent

    def _quick_command(self, command: str) -> str:
        return self._handle_one(clean(command), from_brain=True).text

    def _instant(self, t: str) -> Optional[Reply]:
        for handler in (self._conversation, self._clock, self._media, self._settings, self._power, self._lock):
            reply = handler(t)
            if reply is not None:
                return reply
        return None

    def _needs_agent(self, t: str) -> bool:
        if self.agent is None or self.pending:
            return False
        words = len(t.split())
        if _QUICK_RE.match(t) and words <= 7 and not AGENT_RE.search(t):
            return False
        return bool(AGENT_RE.search(t)) or words > 10

    # ------------------------------------------------------------------ public
    def handle(self, raw: str) -> Reply:
        text = clean(raw)
        if not text:
            return Reply("Yes? I'm listening.", speech="Yes?")
        if self._needs_agent(text):
            instant = self._instant(text)  # time, volume, settings... stay instant
            return instant or Reply(self.agent.run(raw.strip()))
        parts = [p for p in _SPLIT_RE.split(text) if p.strip()]
        if len(parts) > 1:
            replies = [self._handle_one(p.strip()) for p in parts]
            videos = next((r.videos for r in reversed(replies) if r.videos), [])
            return Reply(
                "\n".join(r.text for r in replies),
                speech=" ".join(r.spoken for r in replies),
                videos=videos,
            )
        return self._handle_one(text)

    # ---------------------------------------------------------------- dispatch
    def _handle_one(self, t: str, from_brain: bool = False) -> Reply:
        for handler in (
            self._confirmation,
            self._conversation,
            self._clock,
            self._media,
            self._play,
            self._youtube_search,
            self._web_search,
            self._settings,
            self._open,
            self._close,
            self._notes,
            self._power,
            self._lock,
        ):
            reply = handler(t)
            if reply is not None:
                return reply
        if from_brain:
            return Reply("I'm not sure how to do that yet.")
        if self.agent is not None:
            return Reply(self.agent.run(t))
        return self._ask_brain(t)

    def _ask_brain(self, t: str) -> Reply:
        answer = self.brain.ask(t)
        action = extract_action(answer)
        if action:
            return self._handle_one(clean(action), from_brain=True)
        return Reply(answer)

    # ---------------------------------------------------------------- handlers
    def _confirmation(self, t: str) -> Optional[Reply]:
        if not self.pending:
            return None
        _question, action = self.pending
        self.pending = None
        if re.fullmatch(r"(yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|confirm|yes please|please do)", t):
            return action()
        if re.fullmatch(r"(no|nope|cancel|stop|don't|do not|never ?mind|no thanks)", t):
            return Reply("Okay, cancelled.")
        return None  # something else entirely: drop the question and handle it normally

    def _conversation(self, t: str) -> Optional[Reply]:
        if re.fullmatch(r"(no|nope|no thanks|not now)", t):
            return Reply("Okay.")
        if re.fullmatch(r"(stop|cancel|never ?mind|shut up|be quiet|quiet|silence|that's all|nothing)", t):
            return Reply("Okay.", stop_speaking=True)
        if re.fullmatch(r"(hi|hello|hey|yo|good (morning|afternoon|evening)|hey there|hello there)", t):
            return Reply(random.choice(["Hi! What can I do for you?", "Hello! How can I help?", "Hey! What do you need?"]))
        if re.search(r"\bhow are you\b|\bhow's it going\b|\bwhat's up\b", t):
            return Reply("I'm doing great, thanks for asking! What can I do for you?")
        if re.fullmatch(r"(thanks|thank you|thank you so much|thanks a lot|cool|great|awesome|nice)", t):
            return Reply(random.choice(["You're welcome!", "Anytime!", "Happy to help!"]))
        if re.search(r"\b(who are you|what(?:'s| is) your name|what are you)\b", t):
            return Reply("I'm Ray, your personal assistant. I run right here on your PC.")
        if re.search(r"\b(what can you do|help me|what do you do|help)$", t):
            return Reply(
                "I can open and close apps, search and play YouTube videos, search the web, control your volume "
                "and music, tell the time, remember notes, and answer questions. Try saying: play lofi music.",
            )
        return None

    def _clock(self, t: str) -> Optional[Reply]:
        now = dt.datetime.now()
        if re.search(r"\b(what(?:'s| is)? (?:the )?time|time is it|current time|tell me the time)\b", t):
            return Reply(f"It's {now.strftime('%I:%M %p').lstrip('0')}.")
        if re.search(r"\b(what(?:'s| is)? (?:the |today's )?date|what day is (?:it|today)|today's date)\b", t):
            return Reply(f"Today is {now.strftime('%A, %B')} {now.day}, {now.year}.")
        return None

    def _media(self, t: str) -> Optional[Reply]:
        noun = r"(?:\s+(?:it|this|that|the|my|music|song|video|track|playback|youtube|spotify)){0,3}"
        if re.fullmatch(rf"(?:pause|stop){noun}|stop playing", t) and t != "stop":
            self.system.media("play_pause")
            return Reply("Paused.", speech="")
        if re.fullmatch(rf"(?:resume|unpause|continue){noun}", t):
            self.system.media("play_pause")
            return Reply("Resuming.", speech="")
        if re.fullmatch(rf"(?:next|skip){noun}(?:\s+(?:one|video|song))?", t):
            if self.videos and self.video_index is not None and self.video_index + 1 < len(self.videos):
                return self._play_video(self.video_index + 1)
            self.system.media("next")
            return Reply("Skipping.", speech="")
        if re.fullmatch(rf"(?:previous|go back|back){noun}(?:\s+(?:one|video|song))?", t):
            if self.videos and self.video_index:
                return self._play_video(self.video_index - 1)
            self.system.media("previous")
            return Reply("Going back.", speech="")
        if re.search(r"\b(volume up|turn (?:it |the volume )?up|louder|increase (?:the )?volume|raise (?:the )?volume)\b", t):
            self.system.media("volume_up", repeat=5)
            return Reply("Turning it up.", speech="")
        if re.search(r"\b(volume down|turn (?:it |the volume )?down|quieter|softer|decrease (?:the )?volume|lower (?:the )?volume)\b", t):
            self.system.media("volume_down", repeat=5)
            return Reply("Turning it down.", speech="")
        if re.fullmatch(r"(?:un)?mute(?: (?:the )?(?:volume|sound|audio|it|pc|computer))?", t):
            self.system.media("mute")
            return Reply("Done.", speech="")
        return None

    def _play(self, t: str) -> Optional[Reply]:
        # Answering "Want me to play it?" after a YouTube search
        if re.fullmatch(r"(yes|yeah|yep|yup|sure|ok|okay|do it|go ahead|please do|yes please|play)", t) and self.videos and self.video_index is None:
            return self._play_video(0)
        if not t.startswith("play"):
            return None
        if t == "play":
            if self.videos and self.video_index is None:
                return self._play_video(0)
            self.system.media("play_pause")
            return Reply("Playing.", speech="")

        # "play that video", "play it", "play this one"
        if re.fullmatch(r"play (?:it|that|this|the video|that one|this one|that video|this video|the top one|the result)", t):
            if not self.videos:
                return Reply("Search YouTube for something first, then say play that video.")
            return self._play_video(self.video_index or 0)

        # "play the second one", "play video number 3", "play the last result"
        ordinal = re.fullmatch(
            rf"play (?:the )?(?:video |result |number |video number )?({_ORD})(?: one| video| result| song)?", t
        )
        if ordinal:
            if not self.videos:
                return Reply("Search YouTube for something first, then tell me which one to play.")
            index = ORDINALS[ordinal.group(1)]
            index = len(self.videos) - 1 if index < 0 else index
            if index >= len(self.videos):
                return Reply(f"I only found {len(self.videos)} videos.")
            return self._play_video(index)

        spotify = re.fullmatch(r"play (.+?) on spotify", t)
        if spotify:
            query = spotify.group(1)
            self.system.open_url(f"spotify:search:{quote(query)}")
            return Reply(f"Opening {query} on Spotify.")

        match = re.fullmatch(r"play (?:me )?(?:some |a |the )?(.+?)(?: on youtube| on yt| from youtube)?", t)
        if not match:
            return None
        query = match.group(1)
        try:
            videos = self.search_youtube(query)
        except Exception:
            videos = []
        if not videos:
            self.system.open_url(youtube.results_url(query))
            return Reply(f"I couldn't load results, so I opened a YouTube search for {query}.")
        self.videos = videos
        return self._play_video(0)

    def _play_video(self, index: int) -> Reply:
        video = self.videos[index]
        self.video_index = index
        self.system.open_url(video.url)
        by = f" by {video.channel}" if video.channel else ""
        return Reply(f"Playing {video.title}{by}.", speech=f"Playing {video.title}.", videos=self.videos)

    def _youtube_search(self, t: str) -> Optional[Reply]:
        verbs = r"(?:search|find|look up|look for|show me|search for)"
        match = (
            re.fullmatch(rf"{verbs}\s+(?:on\s+|in\s+)?youtube\s+(?:for\s+)?(.+)", t)
            or re.fullmatch(rf"{verbs}\s+(?:for\s+)?(?:videos? (?:of|about|on)\s+)?(.+?)\s+(?:on|in)\s+youtube", t)
            or re.fullmatch(rf"(?:youtube|{verbs} videos? (?:of|about|on))\s+(.+)", t)
        )
        if not match:
            return None
        query = match.group(1)
        self.system.open_url(youtube.results_url(query))
        try:
            self.videos = self.search_youtube(query)
        except Exception:
            self.videos = []
        self.video_index = None
        if not self.videos:
            return Reply(f"Here are YouTube results for {query}.")
        lines = "\n".join(f"{i + 1}. {v.title}" for i, v in enumerate(self.videos))
        return Reply(
            f"Here's what I found for {query}:\n{lines}\n\nSay \"play that video\" or \"play the second one\".",
            speech=f"Here's what I found. The top result is {self.videos[0].title}. Want me to play it?",
            videos=self.videos,
        )

    def _web_search(self, t: str) -> Optional[Reply]:
        match = re.fullmatch(
            r"(?:search|google|look up|search for|search google for|google search|search the web for|find)\s+"
            r"(?:for\s+)?(.+?)(?:\s+on google|\s+online)?",
            t,
        )
        if not match:
            return None
        query = match.group(1)
        self.system.open_url(f"https://www.google.com/search?q={quote_plus(query)}")
        return Reply(f"Searching the web for {query}.")

    def _open(self, t: str) -> Optional[Reply]:
        match = re.fullmatch(r"(?:open|launch|start|run|go to|visit|bring up|fire up)\s+(?:up\s+)?(?:the\s+|my\s+)?(.+?)(?:\s+app|\s+application|\s+website|\s+folder)?", t)
        if not match:
            return None
        name = match.group(1)
        label = name.title() if len(name) > 3 else name.upper()
        if name in FOLDERS and self.system.open_folder(name):
            return Reply(f"Opening your {name} folder.")
        if name in APPS and self.system.open_app(name):
            return Reply(f"Opening {label}.")
        website = self.system.website_for(name)
        if website:
            self.system.open_url(website)
            return Reply(f"Opening {label}.")
        if self.system.open_app(name):
            return Reply(f"Opening {label}.")
        return Reply(f"I couldn't find an app called {name} on this PC.")

    def _close(self, t: str) -> Optional[Reply]:
        match = re.fullmatch(r"(?:close|quit|exit|kill|shut down)\s+(?:the\s+|my\s+)?(.+?)(?:\s+app|\s+application)?", t)
        if not match or match.group(1) in {"pc", "computer", "laptop", "windows"}:
            return None
        name = match.group(1)
        if self.system.close_app(name):
            return Reply(f"Closed {name}.")
        return Reply(f"{name.title()} doesn't seem to be running.")

    def _notes(self, t: str) -> Optional[Reply]:
        save = re.fullmatch(r"(?:remember|note|take a note|make a note|write down)(?: that)?[:,]?\s+(.+)", t)
        if save:
            self.notes_path.parent.mkdir(parents=True, exist_ok=True)
            with self.notes_path.open("a", encoding="utf-8") as fh:
                fh.write(save.group(1) + "\n")
            return Reply("Got it, I'll remember that.")
        if re.search(r"\b(what do you remember|my notes|show (?:me )?(?:my )?notes|read (?:my )?notes|what did i tell you)\b", t):
            notes = self.notes_path.read_text(encoding="utf-8").splitlines() if self.notes_path.exists() else []
            notes = [n for n in notes if n.strip()]
            if not notes:
                return Reply("You haven't asked me to remember anything yet.")
            return Reply("Here's what you told me:\n- " + "\n- ".join(notes), speech="You told me: " + ". ".join(notes[-5:]))
        return None

    def _settings(self, t: str) -> Optional[Reply]:
        page = re.fullmatch(r"(?:open|show|go to|launch)\s+(?:the\s+|my\s+)?(?:windows\s+)?(.+?)\s+settings?", t)
        if page:
            self.system.open_settings(page.group(1))
            return Reply(f"Opening {page.group(1)} settings.")
        if re.search(r"\b(?:(?:turn on|enable|switch to|use|activate) dark (?:mode|theme)|dark mode on|turn off light mode)\b", t):
            return Reply("Dark mode is on." if self.system.set_dark_mode(True) else "I couldn't change the theme.")
        if re.search(r"\b(?:(?:turn on|enable|switch to|use|activate) light (?:mode|theme)|light mode on|turn off dark mode|disable dark mode)\b", t):
            return Reply("Light mode is on." if self.system.set_dark_mode(False) else "I couldn't change the theme.")
        level = re.search(r"\bbrightness (?:to |at )?(\d{1,3})\s*(?:%|percent)?\b", t)
        if level:
            ok = self.system.set_brightness(int(level.group(1)))
            return Reply(f"Brightness set to {level.group(1)} percent." if ok else "I can't control this screen's brightness.")
        step = re.search(r"\b(brightness up|brighter|increase (?:the )?brightness|brightness down|dimmer|dim the screen|decrease (?:the )?brightness|lower (?:the )?brightness)\b", t)
        if step:
            current = self.system.get_brightness()
            if current is None:
                return Reply("I can't control this screen's brightness.")
            up = any(w in step.group(1) for w in ("up", "brighter", "increase"))
            self.system.set_brightness(current + (20 if up else -20))
            return Reply("Brighter." if up else "Dimmer.", speech="")
        toggle = re.fullmatch(r"turn (on|off) (?:the )?(wi-?fi|bluetooth|airplane mode|hotspot|night light|focus|do not disturb)", t)
        if toggle:
            name = toggle.group(2)
            self.system.open_settings("wifi" if name.startswith("wi") else name)
            return Reply(f"I opened {name} settings. Flip the switch to turn it {toggle.group(1)}.")
        if re.fullmatch(r"(?:take a |take )?(?:screenshot|screen shot|screen capture|snip)", t):
            self.system.screenshot()
            return Reply("Select the area to capture.", speech="")
        return None

    def _power(self, t: str) -> Optional[Reply]:
        device = r"(?:my |the |this )?(?:pc|computer|laptop|system|device)"
        actions = [
            (rf"(?:shut ?down|turn off|power off)(?: {device})?", "shutdown", "shut down"),
            (rf"(?:restart|reboot)(?: {device})?", "restart", "restart"),
            (rf"(?:put {device} to sleep|sleep|go to sleep)", "sleep", "put your PC to sleep"),
            (r"(?:sign|log) (?:me )?out", "sign out", "sign you out"),
        ]
        for pattern, action, words in actions:
            if re.fullmatch(pattern, t):
                def run(a=action, w=words) -> Reply:
                    return Reply(f"Okay, I'll {w} now." if self.system.power(a) else "I couldn't do that.")

                self.pending = (f"Are you sure you want me to {words}?", run)
                return Reply(f"Are you sure you want me to {words}?")
        return None

    def _lock(self, t: str) -> Optional[Reply]:
        if re.fullmatch(r"lock (?:my |the )?(?:pc|computer|screen|laptop|device)", t):
            self.system.lock()
            return Reply("Locking your PC.")
        return None
