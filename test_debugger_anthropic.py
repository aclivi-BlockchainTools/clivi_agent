# test_debugger_anthropic.py
import os, sys, unittest.mock
sys.path.insert(0, os.path.dirname(__file__))
from bartolo.repair.anthropic import repair_with_anthropic

class FakeAnalysis:
    root = "/tmp/repo"; repo_name = "my-repo"
    services = []; top_level_manifests = []; missing_system_deps = []

class FakeStep:
    id = "py-install"; title = "Install"
    command = "pip install -r req.txt"
    cwd = "/tmp"; category = "install"; verify_url = None; verify_port = None


def test_no_api_key_returns_none():
    os.environ.pop("ANTHROPIC_API_KEY", None)
    prior = [{"attempt": 1, "command": "pip install", "returncode": 1,
              "stderr_tail": "ModuleNotFoundError", "result": None, "success": False}]
    with unittest.mock.patch("bartolo.repair.anthropic._read_api_key", return_value=None):
        _sys_prompt = lambda stack, kb_md: "test"
        result = repair_with_anthropic(FakeStep(), prior, "python", "", _sys_prompt)
        assert result is None


def test_anthropic_not_installed_returns_none():
    prior = [{"attempt": 1, "command": "pip install", "returncode": 1,
              "stderr_tail": "ModuleNotFoundError", "result": None, "success": False}]
    _sys_prompt = lambda stack, kb_md: "test"
    with unittest.mock.patch("bartolo.repair.anthropic._read_api_key", return_value="sk-test"):
        with unittest.mock.patch("bartolo.repair.anthropic._make_anthropic_client",
                                 side_effect=ImportError("no anthropic")):
            result = repair_with_anthropic(FakeStep(), prior, "python", "", _sys_prompt)
            assert result is None


def test_anthropic_called_returns_command():
    mock_client = unittest.mock.MagicMock()
    mock_client.messages.create.return_value.content = [
        unittest.mock.MagicMock(text='{"command": "pip install requests", "reason": "missing dep"}')
    ]
    prior = [{"attempt": 1, "command": "pip install -r req.txt",
              "returncode": 1, "stderr_tail": "ModuleNotFoundError", "result": None, "success": False}]
    _sys_prompt = lambda stack, kb_md: "test"
    with unittest.mock.patch("bartolo.repair.anthropic._read_api_key", return_value="sk-test"):
        with unittest.mock.patch("bartolo.repair.anthropic._make_anthropic_client", return_value=mock_client):
            result = repair_with_anthropic(FakeStep(), prior, "python", "", _sys_prompt)
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
