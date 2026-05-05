# test_debugger_types.py
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from agents.debugger import Diagnosis, RepairResult, _read_api_key

def test_diagnosis_fields():
    d = Diagnosis(error_type="missing_dependency", description="No module requests",
                  can_fix_automatically=True, keywords=["requests"])
    assert d.error_type == "missing_dependency"
    assert d.keywords == ["requests"]

def test_repair_result_defaults():
    r = RepairResult(repaired=False, source="none", fix_command=None,
                     diagnosis=None, execution_results=[], repair_attempts=[])
    assert not r.repaired
    assert r.source == "none"

def test_read_api_key_from_env():
    os.environ["ANTHROPIC_API_KEY"] = "sk-test-123"
    key = _read_api_key()
    assert key == "sk-test-123"
    del os.environ["ANTHROPIC_API_KEY"]

passes = 0
for fn_name, fn in list(globals().items()):
    if fn_name.startswith("test_"):
        try:
            fn()
            print(f"  PASS  {fn_name}")
            passes += 1
        except Exception as e:
            print(f"  FAIL  {fn_name}: {e}")
            sys.exit(1)
print(f"\n{passes} tests passed.")
