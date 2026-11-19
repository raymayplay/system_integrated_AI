from types import SimpleNamespace as NS

from ray.agent import Agent, _step_label
from ray.commands import CommandEngine, find_wake_word

from test_ray import FakeBrain, FakeSystem


def text(t):
    return NS(type="text", text=t)


def tool(name, args, id="t1"):
    return NS(type="tool_use", id=id, name=name, input=args)


class FakeClient:
    """Plays back scripted Claude responses and records requests."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def reply(*content, stop="end_turn"):
    return NS(stop_reason=stop, content=list(content))


class FakeBrowser:
    def available(self):
        return True

    def open(self, url):
        self.opened = url
        return "URL: " + url + "\nINTERACTIVE ELEMENTS:\n[1] button \"Apply\""


def make_agent(*responses, answer="yes"):
    system = FakeSystem()
    commands = []
    agent = Agent(system=system, quick_command=lambda c: commands.append(c) or f"did {c}", browser=FakeBrowser(), client=FakeClient(*responses))
    agent.questions = []
    agent.ask_user = lambda q: agent.questions.append(q) or answer
    agent.commands = commands
    return agent


def test_agent_runs_tools_and_answers():
    agent = make_agent(
        reply(tool("quick_command", {"command": "open spotify"}), stop="tool_use"),
        reply(text("Spotify is open.")),
    )
    assert agent.run("open spotify for me") == "Spotify is open."
    assert agent.commands == ["open spotify"]
    request = agent.client.requests[0]
    assert request["model"] == "claude-opus-5-5"
    assert request["fallbacks"] == "default"
    # the tool result goes back to Claude with the matching id
    last = agent.client.requests[1]["messages"][-1]["content"][0]
    assert last["tool_use_id"] == "t1" and last["content"] == "did open spotify"


def test_browser_tools():
    agent = make_agent(
        reply(tool("browser_open", {"url": "linkedin.com/jobs"}), stop="tool_use"),
        reply(text("I found the job page.")),
    )
    agent.run("find jobs")
    assert agent.browser.opened == "linkedin.com/jobs"


def test_powershell_needs_approval():
    agent = make_agent(
        reply(tool("run_powershell", {"command": "Remove-Item x", "reason": "clean up"}), stop="tool_use"),
        reply(text("Okay.")),
        answer="no",
    )
    agent.run("delete x")
    assert agent.questions and not hasattr(agent.system, "ran")
    result = agent.client.requests[1]["messages"][-1]["content"][0]["content"]
    assert "declined" in result


def test_write_file_goes_to_projects(tmp_path, monkeypatch):
    monkeypatch.setattr("ray.agent.PROJECTS_DIR", tmp_path)
    agent = make_agent(
        reply(tool("write_file", {"path": "hello/app.py", "content": "print('hi')"}), stop="tool_use"),
        reply(text("Saved.")),
    )
    agent.run("write a hello world")
    assert (tmp_path / "hello" / "app.py").read_text() == "print('hi')"
    assert agent.questions == []  # inside RayProjects: no confirmation needed


def test_refusal_and_cancel():
    agent = make_agent(reply(stop="refusal"))
    assert "can't" in agent.run("something bad")
    assert agent.messages == []


def test_step_labels():
    assert _step_label("browser_open", {"url": "https://www.linkedin.com/jobs"}) == "Opening the page linkedin.com…"


def engine_with(agent):
    return CommandEngine(system=FakeSystem(), brain=FakeBrain(), search_youtube=lambda q: [], agent=agent)


class RecordingAgent:
    def __init__(self):
        self.asked = []

    def run(self, request):
        self.asked.append(request)
        return "agent answer"


def test_routing_big_tasks_to_agent():
    agent = RecordingAgent()
    engine = engine_with(agent)
    assert engine.handle("Hey Ray, book a table for two at an italian place tonight").text == "agent answer"
    assert engine.handle("apply for the python developer job on linkedin").text == "agent answer"
    assert engine.handle("what's the weather in mumbai").text == "agent answer"


def test_simple_commands_stay_instant():
    agent = RecordingAgent()
    engine = engine_with(agent)
    engine.handle("open spotify")
    engine.handle("volume up")
    engine.handle("what time is it")
    engine.handle("open bluetooth settings")
    assert agent.asked == []
    assert engine.system.settings == ["bluetooth"]


def test_settings_commands():
    engine = engine_with(None)
    engine.handle("turn on dark mode")
    assert engine.system.dark is True
    engine.handle("set brightness to 30 percent")
    assert engine.system.brightness == 30
    assert "Flip the switch" in engine.handle("turn off bluetooth").text


def test_power_needs_confirmation():
    engine = engine_with(None)
    assert engine.handle("restart my pc").text.startswith("Are you sure")
    assert not hasattr(engine.system, "powered")
    engine.handle("yes")
    assert engine.system.powered == "restart"
    engine.handle("shut down the computer")
    assert engine.handle("no").text == "Okay, cancelled."


def test_strict_wake_word_ignores_conversation():
    assert find_wake_word("hey ray open chrome", strict=True) == (True, "open chrome")
    assert find_wake_word("i told my friend ray about it", strict=True)[0] is False
