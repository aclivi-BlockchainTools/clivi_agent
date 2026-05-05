# test_debugger_anthropic.py
import sys, os, tempfile, unittest.mock
sys.path.insert(0, os.path.dirname(__file__))
from agents.debugger import IntelligentDebugger

class FakeAnalysis:
    root = "/tmp/repo"; repo_name = "my-repo"
    services = []; top_level_manifests = []; missing_system_deps = []

class FakeStep:
    id = "py-install"; title = "Install"
    command = "pip install -r req.txt"
    cwd = "/tmp"; category = "install"; verify_url = None; verify_port = None

def test_no_api_key_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test", analysis=FakeAnalysis(), workspace=tmp,
                                   ollama_fn=lambda *a, **kw: {}, kb_dir=tmp)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        with unittest.mock.patch("agents.debugger._read_api_key", return_value=None):
            result = dbg._repair_with_anthropic(FakeStep(), [], "python", "")
            assert result is None

def test_anthropic_not_installed_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test", analysis=FakeAnalysis(), workspace=tmp,
                                   ollama_fn=lambda *a, **kw: {}, kb_dir=tmp)
        with unittest.mock.patch("agents.debugger._read_api_key", return_value="sk-test"):
            with unittest.mock.patch("agents.debugger._make_anthropic_client",
                                     side_effect=ImportError("no anthropic")):
                result = dbg._repair_with_anthropic(FakeStep(), [], "python", "")
                assert result is None

def test_anthropic_called_returns_command():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test", analysis=FakeAnalysis(), workspace=tmp,
                                   ollama_fn=lambda *a, **kw: {}, kb_dir=tmp)
        mock_client = unittest.mock.MagicMock()
        mock_client.messages.create.return_value.content = [
            unittest.mock.MagicMock(text='{"command": "pip install requests", "reason": "missing dep"}')
        ]
        prior = [{"attempt": 1, "command": "pip install -r req.txt",
                  "returncode": 1, "stderr_tail": "ModuleNotFoundError", "result": None, "success": False}]
        with unittest.mock.patch("agents.debugger._read_api_key", return_value="sk-test"):
            with unittest.mock.patch("agents.debugger._make_anthropic_client", return_value=mock_client):
                result = dbg._repair_with_anthropic(FakeStep(), prior, "python", "")
                assert result == "pip install requests"
                assert mock_client.messages.create.called

passes = 0
for fn_name, fn in list(globals().items()):
    if fn_name.startswith("test_"):
        try:
            fn()
            print(f"  PASS  {fn_name}")
            passes += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  FAIL  {fn_name}: {e}")
            sys.exit(1)
print(f"\n{passes} tests passed.")
