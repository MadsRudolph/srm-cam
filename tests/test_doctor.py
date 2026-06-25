"""Tests for the environment doctor (package check + install helper)."""
from gerber2rml import doctor


def test_dist_name_strips_specifiers():
    assert doctor._dist_name("shapely>=2.0") == "shapely"
    assert doctor._dist_name("PySide6>=6.5") == "PySide6"
    assert doctor._dist_name("pyserial>=3.5   # comment") == "pyserial"
    assert doctor._dist_name("PyOpenGL ; python_version>'3'") == "PyOpenGL"


def test_requirements_read_from_pyproject():
    groups = doctor._requirements()
    # the real deps declared in pyproject.toml show up in the right groups
    assert "shapely" in groups["core"] and "gerbonara" in groups["core"]
    assert "PySide6" in groups["gui"] and "pyserial" in groups["gui"]
    assert "pytest" in groups["dev"]


def test_check_passes_when_all_present(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "_installed_version", lambda dist: "1.0")
    rc = doctor.main(["--check"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "All set" in out and "MISSING" not in out


def test_check_reports_missing_and_does_not_install(monkeypatch, capsys):
    def fake_ver(dist):
        return None if dist == "pyqtgraph" else "1.0"
    monkeypatch.setattr(doctor, "_installed_version", fake_ver)
    # guard: --check must never shell out to pip
    monkeypatch.setattr(doctor, "_pip_install",
                        lambda dev: (_ for _ in ()).throw(AssertionError("installed!")))
    rc = doctor.main(["--check"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "pyqtgraph" in out and "[MISSING]" in out


def test_install_path_invokes_pip_then_rechecks(monkeypatch, capsys):
    calls = {"pip": 0}
    state = {"pyqtgraph": None}                  # missing until "installed"

    def fake_ver(dist):
        return state.get(dist, "1.0")

    def fake_pip(dev):
        calls["pip"] += 1
        state["pyqtgraph"] = "0.14.0"            # pip "installs" it
        return 0

    monkeypatch.setattr(doctor, "_installed_version", fake_ver)
    monkeypatch.setattr(doctor, "_pip_install", fake_pip)
    rc = doctor.main([])                         # default: check then install
    out = capsys.readouterr().out
    assert rc == 0 and calls["pip"] == 1
    assert "All set" in out
