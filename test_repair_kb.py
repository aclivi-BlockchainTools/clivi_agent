# test_repair_kb.py
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from agents.debugger import RepairKB

def test_fingerprint_stable():
    kb = RepairKB.__new__(RepairKB)
    fp1 = kb._fingerprint("python", "missing_dependency", "ModuleNotFoundError requests pip")
    fp2 = kb._fingerprint("python", "missing_dependency", "ModuleNotFoundError requests pip")
    assert fp1 == fp2, "fingerprint must be deterministic"
    assert len(fp1) == 12, f"expected 12 chars, got {len(fp1)}"

def test_fingerprint_different_errors():
    kb = RepairKB.__new__(RepairKB)
    fp1 = kb._fingerprint("python", "missing_dependency", "requests pip install")
    fp2 = kb._fingerprint("python", "port_conflict", "address already in use")
    assert fp1 != fp2

def test_keywords_extraction():
    kb = RepairKB.__new__(RepairKB)
    stderr = "Traceback (most recent call last):\n  File 'main.py', line 42\nModuleNotFoundError: No module named 'requests'"
    kws = kb._extract_keywords(stderr)
    assert "ModuleNotFoundError" in kws or "requests" in kws
    assert len(kws) <= 5

def test_save_and_lookup():
    with tempfile.TemporaryDirectory() as tmp:
        kb = RepairKB(kb_dir=tmp)
        kb.save("python", "missing_dependency", ["ModuleNotFoundError", "requests"], "pip install requests", "ollama")
        result = kb.lookup("python", "missing_dependency", "ModuleNotFoundError requests pip")
        assert result is not None
        assert result["fix_command"] == "pip install requests"

def test_lookup_miss():
    with tempfile.TemporaryDirectory() as tmp:
        kb = RepairKB(kb_dir=tmp)
        result = kb.lookup("python", "missing_dependency", "some unknown error xyz")
        assert result is None

def test_markdown_written_on_save():
    with tempfile.TemporaryDirectory() as tmp:
        kb = RepairKB(kb_dir=tmp)
        kb.save("python", "missing_dependency", ["ModuleNotFoundError", "requests"], "pip install requests", "ollama")
        md_path = os.path.join(tmp, "repair_kb_python.md")
        assert os.path.exists(md_path)
        assert "pip install requests" in open(md_path).read()

def test_markdown_for_stack_empty():
    with tempfile.TemporaryDirectory() as tmp:
        kb = RepairKB(kb_dir=tmp)
        assert kb.markdown_for_stack("elixir") == ""

def test_markdown_for_stack_after_save():
    with tempfile.TemporaryDirectory() as tmp:
        kb = RepairKB(kb_dir=tmp)
        kb.save("python", "missing_dependency", ["requests"], "pip install requests", "ollama")
        md = kb.markdown_for_stack("python")
        assert "pip install requests" in md

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
