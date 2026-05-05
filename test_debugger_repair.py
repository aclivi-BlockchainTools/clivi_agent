# test_debugger_repair.py
import sys, os, tempfile, time
sys.path.insert(0, os.path.dirname(__file__))
from agents.debugger import IntelligentDebugger, RepairResult

def make_ollama(response):
    def fn(model, messages, schema=None, timeout=180):
        return response
    return fn

class FakeAnalysis:
    root = "/tmp/repo"; repo_name = "my-repo"
    services = []; top_level_manifests = []; missing_system_deps = []

class FakeStep:
    id = "py-install"; title = "Install"; command = "pip install -r req.txt"
    cwd = "/tmp"; category = "install"; verify_url = None; verify_port = None

class FakeResult:
    command = "pip install -r req.txt"; cwd = "/tmp"; returncode = 1
    stdout = ""; stderr = "ModuleNotFoundError: requests"
    step_id = "py-install"; repaired = False
    started_at = 0.0; finished_at = 0.0

def make_success_result():
    r = FakeResult(); r.returncode = 0; return r

def test_kb_hit_returns_repaired_source_kb():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(
            model="test", analysis=FakeAnalysis(), workspace=tmp,
            ollama_fn=make_ollama({"diagnosis": "dep", "likely_cause": "missing_dependency",
                                    "can_be_fixed_automatically": True}),
            kb_dir=tmp, max_repair_attempts=1,
        )
        dbg.kb.save("unknown", "missing_dependency", ["requests"], "pip install requests", "test")
        dbg._run_repair_cmd = lambda cmd, step, attempt: (make_success_result(), True)
        result = dbg.repair(FakeStep(), FakeResult(), approve_all=True)
        assert result.repaired is True
        assert result.source == "kb"

def test_ollama_success_returns_repaired_source_ollama():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(
            model="test", analysis=FakeAnalysis(), workspace=tmp,
            ollama_fn=make_ollama({"diagnosis": "dep", "likely_cause": "missing_dependency",
                                    "can_be_fixed_automatically": True,
                                    "command": "pip install requests", "reason": "dep"}),
            kb_dir=tmp, max_repair_attempts=1,
        )
        dbg._run_repair_cmd = lambda cmd, step, attempt: (make_success_result(), True)
        result = dbg.repair(FakeStep(), FakeResult(), approve_all=True)
        assert result.repaired is True
        assert result.source == "ollama"

def test_all_fail_returns_not_repaired():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(
            model="test", analysis=FakeAnalysis(), workspace=tmp,
            ollama_fn=make_ollama({"diagnosis": "dep", "likely_cause": "missing_dependency",
                                    "can_be_fixed_automatically": True,
                                    "command": "false", "reason": "test"}),
            kb_dir=tmp, max_repair_attempts=1,
        )
        dbg._run_repair_cmd = lambda cmd, step, attempt: (FakeResult(), False)
        dbg._repair_with_anthropic = lambda *a, **kw: None
        dbg._escalate = lambda *a, **kw: None
        result = dbg.repair(FakeStep(), FakeResult(), approve_all=True)
        assert result.repaired is False
        assert result.source == "none"

def test_result_to_step_error_repaired_false():
    with tempfile.TemporaryDirectory() as tmp:
        dbg = IntelligentDebugger(
            model="test", analysis=FakeAnalysis(), workspace=tmp,
            ollama_fn=make_ollama({"diagnosis": "dep", "likely_cause": "other",
                                    "can_be_fixed_automatically": False,
                                    "command": "false", "reason": "test"}),
            kb_dir=tmp, max_repair_attempts=1,
        )
        dbg._run_repair_cmd = lambda cmd, step, attempt: (FakeResult(), False)
        dbg._repair_with_anthropic = lambda *a, **kw: None
        dbg._escalate = lambda *a, **kw: None
        repair_result = dbg.repair(FakeStep(), FakeResult(), approve_all=True)
        assert isinstance(repair_result, RepairResult)
        assert repair_result.repaired is False

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
