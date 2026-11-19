"""Live YouTube search without an API key.

Fetches the public results page and reads the video list embedded in it, so
Ray can play the first result directly or remember results for follow-ups
like "play the second one".
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator, List
from urllib.parse import quote_plus

SEARCH_URL = "https://www.youtube.com/results?search_query={query}"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    # Skips the EU cookie-consent interstitial.
    "Cookie": "CONSENT=YES+1; SOCS=CAI",
}


@dataclass
class Video:
    video_id: str
    title: str
    channel: str = ""
    duration: str = ""

    @property
    def url(self) -> str:
        return WATCH_URL.format(video_id=self.video_id)


def results_url(query: str) -> str:
    return SEARCH_URL.format(query=quote_plus(query.strip()))


def _text(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    if "simpleText" in node:
        return str(node["simpleText"])
    return "".join(str(run.get("text", "")) for run in node.get("runs", []) if isinstance(run, dict))


def _walk_video_renderers(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        renderer = node.get("videoRenderer")
        if isinstance(renderer, dict) and renderer.get("videoId"):
            yield renderer
        for value in node.values():
            yield from _walk_video_renderers(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_video_renderers(item)


def parse_results(html: str, limit: int = 5) -> List[Video]:
    videos: List[Video] = []
    seen: set[str] = set()

    match = re.search(r"(?:var ytInitialData|window\[\"ytInitialData\"\])\s*=\s*(\{.+?\});\s*</script>", html, re.S)
    if match:
        try:
            data = json.loads(match.group(1))
        except ValueError:
            data = None
        for renderer in _walk_video_renderers(data):
            video_id = renderer["videoId"]
            if video_id in seen:
                continue
            seen.add(video_id)
            videos.append(
                Video(
                    video_id=video_id,
                    title=_text(renderer.get("title")) or "Untitled video",
                    channel=_text(renderer.get("ownerText")),
                    duration=_text(renderer.get("lengthText")),
                )
            )
            if len(videos) >= limit:
                return videos

    if not videos:  # Page layout changed: fall back to bare video ids.
        for video_id in re.findall(r'"videoId":"([\w-]{11})"', html):
            if video_id not in seen:
                seen.add(video_id)
                videos.append(Video(video_id=video_id, title=f"Result {len(videos) + 1}"))
            if len(videos) >= limit:
                break
    return videos


def search(query: str, limit: int = 5, timeout: float = 8.0) -> List[Video]:
    request = urllib.request.Request(results_url(query), headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="replace")
    return parse_results(html, limit=limit)
