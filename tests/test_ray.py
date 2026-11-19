import json

import pytest

from ray import brain as brain_module
from ray import youtube
from ray.brain import Brain, extract_action
from ray.commands import CommandEngine, find_wake_word
from ray.youtube import Video


class FakeSystem:
    def __init__(self):
        self.urls, self.apps, self.closed, self.keys, self.folders = [], [], [], [], []

    def open_url(self, url):
        self.urls.append(url)
        return True

    def website_for(self, name):
        from ray.system import System

        return System.website_for(self, name)

    def open_folder(self, name):
        self.folders.append(name)
        return True

    def open_app(self, name):
        self.apps.append(name)
        return name != "nonexistent thing"

    def close_app(self, name):
        self.closed.append(name)
        return True

    def media(self, action, repeat=1):
        self.keys.append((action, repeat))
        return True

    def lock(self):
        return True


class FakeBrain:
    def __init__(self, answer="Paris is the capital of France."):
        self.answer, self.asked, self.model = answer, [], "test"

    def ask(self, prompt):
        self.asked.append(prompt)
        return self.answer


VIDEOS = [Video("aaaaaaaaaaa", "Lofi Beats", "Chill Channel", "1:00:00"), Video("bbbbbbbbbbb", "Second Video"), Video("ccccccccccc", "Third Video")]


@pytest.fixture
def ray(tmp_path):
    searches = []

    def fake_search(query):
        searches.append(query)
        return list(VIDEOS)

    engine = CommandEngine(system=FakeSystem(), brain=FakeBrain(), notes_path=tmp_path / "notes.txt", search_youtube=fake_search)
    engine.searches = searches
    return engine


@pytest.mark.parametrize(
    "heard, command",
    [
        ("hey ray open spotify", "open spotify"),
        ("Hey Ray, what time is it?", "what time is it"),
        ("okay rey play music", "play music"),
        ("hey ray", ""),
    ],
)
def test_wake_word(heard, command):
    assert find_wake_word(heard) == (True, command)


def test_no_wake_word():
    assert find_wake_word("open spotify")[0] is False


def test_play_on_youtube_plays_first_result(ray):
    reply = ray.handle("Hey Ray, play lofi beats on YouTube")
    assert ray.searches == ["lofi beats"]
    assert ray.system.urls == ["https://www.youtube.com/watch?v=aaaaaaaaaaa"]
    assert "Lofi Beats" in reply.text


def test_search_youtube_then_play_that_video(ray):
    reply = ray.handle("search youtube for cooking pasta")
    assert ray.system.urls[0] == youtube.results_url("cooking pasta")
    assert reply.videos and reply.spoken.endswith("?")
    ray.handle("play that video")
    assert ray.system.urls[-1].endswith("aaaaaaaaaaa")


@pytest.mark.parametrize("phrase, video_id", [("play the second one", "bbbbbbbbbbb"), ("play number 3", "ccccccccccc"), ("play the last video", "ccccccccccc"), ("yes", "aaaaaaaaaaa")])
def test_pick_result(ray, phrase, video_id):
    ray.handle("find cats on youtube")
    ray.handle(phrase)
    assert ray.system.urls[-1].endswith(video_id)


def test_next_video_moves_through_results(ray):
    ray.handle("play cats")
    ray.handle("next video")
    assert ray.system.urls[-1].endswith("bbbbbbbbbbb")


def test_play_that_video_without_search(ray):
    assert "first" in ray.handle("play that video").text
    assert ray.system.urls == []


def test_open_app_and_website(ray):
    ray.handle("can you open spotify please")
    assert ray.system.apps == ["spotify"]
    ray.handle("open youtube")
    assert ray.system.urls == ["https://www.youtube.com"]
    ray.handle("open downloads")
    assert ray.system.folders == ["downloads"]


def test_unknown_app(ray):
    assert "couldn't find" in ray.handle("open nonexistent thing").text


def test_multiple_commands(ray):
    ray.handle("open notepad and then play tom and jerry")
    assert ray.system.apps == ["notepad"]
    assert ray.searches == ["tom and jerry"]


def test_media_and_volume(ray):
    ray.handle("pause the video")
    ray.handle("volume up")
    ray.handle("mute")
    assert ray.system.keys == [("play_pause", 1), ("volume_up", 5), ("mute", 1)]


def test_close_app(ray):
    ray.handle("close chrome")
    assert ray.system.closed == ["chrome"]


def test_web_search(ray):
    ray.handle("search for weather in tokyo")
    assert ray.system.urls == ["https://www.google.com/search?q=weather+in+tokyo"]


def test_notes(ray):
    ray.handle("remember that my wifi password is on the fridge")
    assert "fridge" in ray.handle("what do you remember").text


def test_questions_go_to_brain(ray):
    assert ray.handle("what is the capital of france").text.startswith("Paris")


def test_brain_can_trigger_actions(ray):
    ray.brain.answer = "ACTION: play relaxing piano music on youtube"
    ray.handle("put on something relaxing")
    assert ray.searches == ["relaxing piano music"]


def test_youtube_parser():
    data = {"contents": [{"videoRenderer": {"videoId": "abcdefghijk", "title": {"runs": [{"text": "Hello"}]},
                                            "ownerText": {"runs": [{"text": "Chan"}]}, "lengthText": {"simpleText": "3:21"}}}]}
    html = f"<script>var ytInitialData = {json.dumps(data)};</script>"
    assert youtube.parse_results(html) == [Video("abcdefghijk", "Hello", "Chan", "3:21")]


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.body


def test_brain_uses_ollama_chat_and_strips_thinking(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout):
        sent["url"], sent["payload"] = request.full_url, json.loads(request.data)
        return FakeResponse({"message": {"content": "<think>hmm</think>**Hello** there"}})

    monkeypatch.setattr(brain_module.urllib.request, "urlopen", fake_urlopen)
    b = Brain(base_url="http://localhost:11434", model="qwen3:8b")
    assert b.ask("hi") == "Hello there"
    assert sent["url"] == "http://localhost:11434/api/chat"
    assert sent["payload"]["model"] == "qwen3:8b" and sent["payload"]["think"] is False


def test_brain_offline_message(monkeypatch):
    def fail(*_a, **_k):
        raise OSError("refused")

    monkeypatch.setattr(brain_module.urllib.request, "urlopen", fail)
    assert "Ollama" in Brain().ask("hi")


def test_extract_action():
    assert extract_action("ACTION: open chrome") == "open chrome"
    assert extract_action("Just chatting") is None
