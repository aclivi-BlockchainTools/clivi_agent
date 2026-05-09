# test_router.py
import sys
sys.path.insert(0, "/home/usuari/universal-agent")
from bartolo_router import classify_l1, classify

def test_temps_data():
    assert classify_l1("quina hora és?") == "temps_data"
    assert classify_l1("What time is it?") == "temps_data"
    assert classify_l1("quina data tenim avui?") == "temps_data"

def test_info_sistema():
    assert classify_l1("docker ps") == "info_sistema"
    assert classify_l1("quina versió de docker tens?") == "info_sistema"
    assert classify_l1("quins processos corren?") == "info_sistema"
    assert classify_l1("quant d'espai lliure hi ha?") == "info_sistema"
    assert classify_l1("ollama list") == "info_sistema"

def test_munta_repo():
    assert classify_l1("munta https://github.com/tiangolo/fastapi") == "munta_repo"
    assert classify_l1("instal·la el repo github.com/foo/bar") == "munta_repo"
    assert classify_l1("clona https://github.com/x/y i arrenca-ho") == "munta_repo"

def test_gestio_docker():
    assert classify_l1("actualitza open-webui") == "gestio_docker"
    assert classify_l1("docker pull open-webui") == "gestio_docker"
    assert classify_l1("actualitza el container open-webui") == "gestio_docker"

def test_cerca_web():
    assert classify_l1("cerca a internet com funciona fastapi") == "cerca_web"
    assert classify_l1("busca informació sobre langchain") == "cerca_web"

def test_no_match_returns_none():
    assert classify_l1("hola, com estàs?") is None
    assert classify_l1("explica'm python") is None
    assert classify_l1("escriu-me un poema") is None

def test_classify_dispatch():
    """Test del punt d'entrada unificat classify()."""
    r = classify("quina hora és?")
    assert r["intent"] == "temps_data", f"esperava temps_data, got {r['intent']}"
    assert r["source"] == "l1"

    r = classify("docker ps")
    assert r["intent"] == "info_sistema"
    assert r["source"] == "l1"
    assert r["cmd"] is not None, "hauria d'extreure comanda"

    r = classify("munta https://github.com/tiangolo/fastapi")
    assert r["intent"] == "munta_repo"
    assert r["repo_url"] == "https://github.com/tiangolo/fastapi"

def test_l2_fallback_conversa():
    """L2: frase ambigua sense patró L1 → algun intent vàlid."""
    r = classify("hola, com estàs avui?")
    assert r["intent"] in {"conversa", "temps_data", "info_sistema",
                           "munta_repo", "gestio_docker", "cerca_web"}
    assert r["source"] == "l2"

def test_l2_info_with_cmd():
    """L2: pregunta de sistema sense patró L1 exacte."""
    r = classify("quanta memòria RAM hi ha lliure al sistema?")
    # L2 pot retornar info_sistema o conversa — ambdós són vàlids
    assert r["intent"] in {"info_sistema", "conversa"}
    # Si retorna info_sistema, ha de tenir cmd
    if r["intent"] == "info_sistema":
        assert r["cmd"] is not None

if __name__ == "__main__":
    tests = [test_temps_data, test_info_sistema, test_munta_repo,
             test_gestio_docker, test_cerca_web, test_no_match_returns_none,
             test_classify_dispatch, test_l2_fallback_conversa, test_l2_info_with_cmd]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ⚠️  {t.__name__} ERROR: {e}")
            failed += 1
    print(f"\n{len(tests)-failed}/{len(tests)} tests passats")
    sys.exit(1 if failed else 0)
