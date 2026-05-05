# test_debugger_diagnose.py
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from agents.debugger import IntelligentDebugger, Diagnosis

def fake_ollama(model, messages, schema=None, timeout=180):
    return {"diagnosis": "missing requests library", "likely_cause": "missing_dependency",
            "can_be_fixed_automatically": True}

class FakeAnalysis:
    root = "/tmp/repo"; repo_name = "my-repo"
    services = []; top_level_manifests = ["requirements.txt"]; missing_system_deps = []

class FakeStep:
    id = "py-install"; title = "Install deps"
    command = "pip install -r requirements.txt"
    cwd = "/tmp/repo"; category = "install"; verify_url = None; verify_port = None

class FakeResult:
    command = "pip install -r requirements.txt"; cwd = "/tmp/repo"
    returncode = 1; stdout = ""
    stderr = "ModuleNotFoundError: No module named 'requests'"

def test_diagnose_returns_diagnosis():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test-model", analysis=FakeAnalysis(),
                                   workspace=tmp, ollama_fn=fake_ollama, kb_dir=tmp)
        d = dbg._diagnose(FakeStep(), FakeResult())
        assert isinstance(d, Diagnosis)
        assert d.error_type == "missing_dependency"
        assert "missing requests" in d.description

def test_diagnose_ollama_failure_returns_default():
    def bad_ollama(*a, **kw):
        raise RuntimeError("connection refused")
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test-model", analysis=FakeAnalysis(),
                                   workspace=tmp, ollama_fn=bad_ollama, kb_dir=tmp)
        d = dbg._diagnose(FakeStep(), FakeResult())
        assert isinstance(d, Diagnosis)
        assert d.error_type == "other"

def test_build_system_prompt_contains_stack_and_rules():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test-model", analysis=FakeAnalysis(),
                                   workspace=tmp, ollama_fn=fake_ollama, kb_dir=tmp)
        prompt = dbg._build_system_prompt("python", "")
        assert "python" in prompt.lower()
        assert "Linux" in prompt or "linux" in prompt.lower()
        assert "sudo" in prompt

def test_build_system_prompt_includes_kb():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(model="test-model", analysis=FakeAnalysis(),
                                   workspace=tmp, ollama_fn=fake_ollama, kb_dir=tmp)
        prompt = dbg._build_system_prompt("python", "## missing_dependency\nFix: pip install requests")
        assert "pip install requests" in prompt

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
