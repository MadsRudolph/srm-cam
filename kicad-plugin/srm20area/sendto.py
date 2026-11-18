"""Send the board to SRM-CAM: plot it, then open it there. Pure.

No pcbnew and no wx, so it imports and tests anywhere; the button in
``action_send_to_srmcam.py`` is the only part that touches KiCad. Written for
the Python KiCad ships (3.9 on some builds), so no newer syntax.

The plot is made inside KiCad (``plot.py``); ``kicad-cli`` (:func:`export`)
is the fallback for a KiCad whose scripting API does not match. The files
land in a ``srm-cam`` folder beside the board, named the way SRM-CAM's
loader looks for them (``<board>-B_Cu.gbl``, ``<board>-Edge_Cuts.gm1``,
``<board>-PTH.drl`` ...).

SRM-CAM leaves ``launch.json`` in this plugin's folder when it installs it:
how to start SRM-CAM, and where a running one listens (gui2/handoff.py).
"""
import json
import os
import shutil
import socket
import subprocess
import sys

LAUNCH_FILE = "launch.json"
OUT_DIRNAME = "srm-cam"

# Every layer SRM-CAM reads: copper both sides, the outline, the mask and
# silkscreen layers its laser export can use, and the paste layers its
# stencil job cuts.
LAYERS = ["F.Cu", "B.Cu", "Edge.Cuts", "F.Mask", "B.Mask",
          "F.Silkscreen", "B.Silkscreen", "F.Paste", "B.Paste"]

# What a previous send left in the output folder. Cleared first, so a layer
# or drill file the board no longer has cannot linger and be read again.
# Only plot files: method.json (the board's method, methods.py) lives in the
# same folder and is kept.
_PLOTTED = (".gtl", ".gbl", ".gm1", ".gts", ".gbs", ".gto", ".gbo", ".gtp",
            ".gbp", ".gbr", ".drl", ".gbrjob")


class SendError(RuntimeError):
    pass


# --------------------------------------------------------------- kicad-cli
def find_kicad_cli(executable=None, platform=None, which=shutil.which,
                   exists=os.path.isfile):
    """Path to ``kicad-cli``, or None.

    Looked for beside the KiCad that is running this plugin first, so the
    plot is made by the same KiCad version that has the board open.
    """
    executable = sys.executable if executable is None else executable
    platform = sys.platform if platform is None else platform
    name = "kicad-cli.exe" if platform.startswith("win") else "kicad-cli"
    found = []
    path = os.path.abspath(executable)
    if platform == "darwin" and ".app/Contents/" in path:
        app = path[:path.index(".app/Contents/") + len(".app")]
        found.append(os.path.join(app, "Contents", "MacOS", name))
    found.append(os.path.join(os.path.dirname(path), name))
    if platform == "darwin":
        found.append("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
    for f in found:
        if exists(f):
            return f
    return which("kicad-cli")


def output_dir(board_file):
    """The folder a send plots into: ``srm-cam`` beside the board."""
    return os.path.join(os.path.dirname(os.path.abspath(board_file)),
                        OUT_DIRNAME)


def board_copy_path(tmp_dir, board_file):
    """Where the plugin saves the board as it is on screen. Same file name,
    so the plotted files are named after the board."""
    return os.path.join(tmp_dir, os.path.basename(board_file))


def copy_project_file(board_file, copy):
    """Put the project file beside the copy, so text variables in the
    silkscreen resolve the same as they do in the editor."""
    pro = os.path.splitext(board_file)[0] + ".kicad_pro"
    if os.path.isfile(pro) and os.path.abspath(copy) != os.path.abspath(
            board_file):
        shutil.copyfile(pro, os.path.splitext(copy)[0] + ".kicad_pro")


def _run(argv, run):
    try:
        r = run(argv, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        raise SendError("%s failed: %s" % (os.path.basename(argv[0]), e))
    if r.returncode != 0:
        raise SendError("%s\n\n%s" % (" ".join(argv[1:4]),
                                      (r.stderr or r.stdout or "").strip()))
    return r


def clear_plotted(out_dir):
    """Make ``out_dir`` and empty it of what an earlier send plotted."""
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        p = os.path.join(out_dir, f)
        if os.path.isfile(p) and os.path.splitext(f)[1].lower() in _PLOTTED:
            os.remove(p)
    return out_dir


def check_plotted(out_dir):
    """The plot has the one layer SRM-CAM cannot do without."""
    if not any(f.lower().endswith(".gbl") or "-b_cu." in f.lower()
               for f in os.listdir(out_dir)):
        raise SendError("KiCad plotted no B.Cu layer into %s" % out_dir)


def export(board_file, out_dir, cli, run=subprocess.run):
    """Plot Gerbers and drill files for ``board_file`` into ``out_dir`` with
    ``kicad-cli`` - the fallback when the in-process plot (plot.py) does not
    work with this KiCad."""
    clear_plotted(out_dir)
    out = out_dir.rstrip("/\\") + os.sep
    _run([cli, "pcb", "export", "gerbers", "--output", out,
          "--layers", ",".join(LAYERS), board_file], run)
    drill = [cli, "pcb", "export", "drill", "--output", out]
    try:
        _run(drill + ["--excellon-separate-th", board_file], run)
    except SendError:
        _run(drill + [board_file], run)       # older KiCad: one combined file
    check_plotted(out_dir)
    return out_dir


# -------------------------------------------------------------- SRM-CAM
def read_launch_info(plugin_dir):
    """What SRM-CAM wrote about itself when it installed the plugin, or {}."""
    try:
        with open(os.path.join(plugin_dir, LAUNCH_FILE), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def ask_running(address, path, timeout=2.0):
    """Hand ``path`` to a running SRM-CAM over its socket.

    Returns its answer (``ok`` or ``busy``), or None when nothing listens.
    POSIX only; on Windows the launched copy forwards it instead.
    """
    if not address or not hasattr(socket, "AF_UNIX"):
        return None
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(address)
        s.sendall((json.dumps({"open": path}) + "\n").encode("utf-8"))
        answer = b""
        while not answer.endswith(b"\n"):
            chunk = s.recv(64)
            if not chunk:
                break
            answer += chunk
        return answer.decode("utf-8", "replace").strip() or "ok"
    except OSError:
        return None
    finally:
        s.close()


def _launch_argv(info, path, platform):
    app = info.get("app")
    if platform == "darwin" and app and os.path.isdir(app):
        return ["open", "-a", app, "--args", path]
    argv = list(info.get("argv") or [])
    if argv and os.path.exists(argv[0]):
        return argv + [path]
    if platform == "darwin":
        return ["open", "-a", "SRM-CAM", "--args", path]
    return None


def open_in_srmcam(path, info, platform=None, popen=subprocess.Popen,
                   ask=ask_running):
    """Open ``path`` in SRM-CAM. Returns ``"sent"`` (to the running copy),
    ``"started"``, ``"busy"`` (a run is going; not loaded) or ``"missing"``."""
    platform = sys.platform if platform is None else platform
    answer = ask(info.get("address"), path)
    if answer == "busy":
        return "busy"
    if answer is not None:
        app = info.get("app")
        if platform == "darwin" and app and os.path.isdir(app):
            popen(["open", "-a", app])          # bring the window forward
        return "sent"
    argv = _launch_argv(info, path, platform)
    if argv is None:
        return "missing"
    kw = {}
    if platform.startswith("win"):
        kw["creationflags"] = 0x00000008        # DETACHED_PROCESS
    else:
        kw["start_new_session"] = True
    # SRM-CAM keeps its own log; nothing it prints belongs in KiCad's console.
    popen(argv, close_fds=True, stdin=subprocess.DEVNULL,
          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    return "started"
