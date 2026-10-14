import json
import urllib.error

from pew import LocalPrivateAssistant


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def test_lists_all_installed_ollama_models(tmp_path, monkeypatch):
    assistant = LocalPrivateAssistant(workspace_root=str(tmp_path))

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://127.0.0.1:11434/api/tags"
        assert timeout == 4
        return FakeResponse({"models": [{"name": "qwen2.5:3b"}, {"name": "llama3.2:3b"}]})

    monkeypatch.setattr("pew.urllib.request.urlopen", fake_urlopen)

    assert assistant.list_ollama_models() == ["qwen2.5:3b", "llama3.2:3b"]


def test_uses_selected_local_model_for_generation(tmp_path, monkeypatch):
    assistant = LocalPrivateAssistant(workspace_root=str(tmp_path))
    assistant.selected_model = "llama3.2:3b"
    sent = {}

    def fake_urlopen(request, timeout):
        sent["url"] = request.full_url
        sent["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"response": "Local response"})

    monkeypatch.setattr("pew.urllib.request.urlopen", fake_urlopen)

    assert assistant.ask_local_ollama("Summarize this locally") == "Local response"
    assert sent["url"] == "http://127.0.0.1:11434/api/generate"
    assert sent["payload"]["model"] == "llama3.2:3b"
    assert sent["payload"]["stream"] is False


def test_ray_defaults_to_qwen3_8b(tmp_path, monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    assistant = LocalPrivateAssistant(workspace_root=str(tmp_path))

    assert assistant.selected_model == "qwen3:8b"


def test_ollama_connection_failure_is_reported_to_user(tmp_path, monkeypatch):
    assistant = LocalPrivateAssistant(workspace_root=str(tmp_path))

    def fail_urlopen(_request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("pew.urllib.request.urlopen", fail_urlopen)

    result = assistant.list_ollama_models
    try:
        result()
    except RuntimeError as exc:
        assert "Ollama is not responding" in str(exc)
        assert "connection refused" in str(exc)
    else:
        raise AssertionError("Expected Ollama connection failure to be surfaced")


def test_no_selected_model_uses_first_installed_model(tmp_path, monkeypatch):
    assistant = LocalPrivateAssistant(workspace_root=str(tmp_path))
    assistant.selected_model = ""
    calls = []

    monkeypatch.setattr(assistant, "list_ollama_models", lambda: ["qwen2.5:3b"])

    def fake_urlopen(request, timeout):
        calls.append(json.loads(request.data.decode("utf-8"))["model"])
        return FakeResponse({"response": "Ready"})

    monkeypatch.setattr("pew.urllib.request.urlopen", fake_urlopen)

    assert assistant.ask_local_ollama("Explain this") == "Ready"
    assert calls == ["qwen2.5:3b"]


def test_ai_command_forwards_arbitrary_prompt_to_ollama(tmp_path, monkeypatch):
    assistant = LocalPrivateAssistant(workspace_root=str(tmp_path))
    sent = []
    monkeypatch.setattr(
        assistant,
        "ask_local_ollama",
        lambda prompt: sent.append(prompt) or "Model answer",
    )

    assert assistant.handle_command("/ai Tell me a story") == "Model answer"
    assert sent == ["Tell me a story"]


def test_common_japanese_translation_works_without_a_network_translator(tmp_path):
    assistant = LocalPrivateAssistant(workspace_root=str(tmp_path))

    assert assistant.translate_text("I like you", "ja") == "私はあなたが好きです"
    assert assistant.translate_text("I love you", "ja") == "愛してる"
    assert assistant.handle_command("what is i like you in japanese") == "私はあなたが好きです"
