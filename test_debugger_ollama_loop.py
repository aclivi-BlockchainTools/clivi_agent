# test_debugger_ollama_loop.py
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from agents.debugger import IntelligentDebugger

call_count = [0]
suggested = ["pip install requests", "pip install -r requirements.txt"]

def fake_ollama_seq(model, messages, schema=None, timeout=180):
    i = call_count[0]
    call_count[0] += 1
    return {"command": suggested[i % 2], "reason": "install missing dep"}

class FakeAnalysis:
    root = "/tmp/repo"; repo_name = "my-repo"
    services = []; top_level_manifests = []; missing_system_deps = []

class FakeStep:
    id = "py-install"; title = "Install"; command = "pip install -r req.txt"
    cwd = "/tmp"; category = "install"; verify_url = None; verify_port = None

class FakeResult:
    command = "pip install -r req.txt"; cwd = "/tmp"; returncode = 1
    stdout = ""; stderr = "ModuleNotFoundError: No module named 'requests'"
    step_id = "py-install"; repaired = False
    started_at = 0.0; finished_at = 0.0

def test_loop_makes_n_attempts_on_failure():
    call_count[0] = 0
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test", analysis=FakeAnalysis(), workspace=tmp,
                                   ollama_fn=fake_ollama_seq, kb_dir=tmp, max_repair_attempts=2)
        dbg._run_repair_cmd = lambda cmd, step, attempt: (FakeResult(), False)
        attempts = dbg._repair_loop_ollama(FakeStep(), FakeResult(), "python", "")
        assert len(attempts) == 2
        assert call_count[0] == 2

def test_loop_stops_on_success():
    call_count[0] = 0
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test", analysis=FakeAnalysis(), workspace=tmp,
                                   ollama_fn=fake_ollama_seq, kb_dir=tmp, max_repair_attempts=2)
        success_result = FakeResult()
        success_result.returncode = 0
        dbg._run_repair_cmd = lambda cmd, step, attempt: (success_result, True)
        attempts = dbg._repair_loop_ollama(FakeStep(), FakeResult(), "python", "")
        assert len(attempts) == 1
        assert attempts[0]["success"] is True
        assert call_count[0] == 1

def test_loop_history_grows():
    call_count[0] = 0
    captured_messages = []
    def capturing_ollama(model, messages, schema=None, timeout=180):
        captured_messages.append(list(messages))
        i = call_count[0]; call_count[0] += 1
        return {"command": suggested[i % 2], "reason": "test"}
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test", analysis=FakeAnalysis(), workspace=tmp,
                                   ollama_fn=capturing_ollama, kb_dir=tmp, max_repair_attempts=2)
        dbg._run_repair_cmd = lambda cmd, step, attempt: (FakeResult(), False)
        dbg._repair_loop_ollama(FakeStep(), FakeResult(), "python", "")
        assert len(captured_messages[1]) > len(captured_messages[0])

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
