"""Manages one R process and speaks the Ryzo kernel protocol with it.

R is started as an interactive process. The IDE sends requests over a local
TCP socket; R answers with framed JSON on stdout. Plain stdout/stderr text is
user output. See ryzo/kernel/ryzo_kernel.R for the other side.
"""

import json
import os
import secrets
import shlex
import shutil
import signal
import sys

from PySide6 import QtCore, QtNetwork

from ryzo import KERNEL_SCRIPT

FRAME_START = b"\x02RYZO"
FRAME_END = b"\x03"


def _prefer_rterm(path):
    """On Windows R.exe is only a launcher; talk to Rterm.exe directly."""
    if path and sys.platform.startswith("win") and os.path.basename(path).lower() == "r.exe":
        rterm = os.path.join(os.path.dirname(path), "Rterm.exe")
        if os.path.exists(rterm):
            return rterm
        rterm = os.path.join(os.path.dirname(path), "x64", "Rterm.exe")
        if os.path.exists(rterm):
            return rterm
    return path


def find_r_executable(exe):
    """Resolve the R executable, also looking in common install locations."""
    return _prefer_rterm(_find_r_executable(exe))


def _find_r_executable(exe):
    if os.path.isabs(exe) and os.path.exists(exe):
        return exe
    found = shutil.which(exe)
    if found:
        return found
    candidates = []
    if sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            rdir = os.path.join(base, "R")
            if os.path.isdir(rdir):
                for v in sorted(os.listdir(rdir), reverse=True):
                    candidates.append(os.path.join(rdir, v, "bin", "x64", "Rterm.exe"))
                    candidates.append(os.path.join(rdir, v, "bin", "R.exe"))
    elif sys.platform == "darwin":
        candidates += ["/Library/Frameworks/R.framework/Resources/bin/R",
                       "/opt/homebrew/bin/R", "/usr/local/bin/R"]
    else:
        candidates += ["/usr/bin/R", "/usr/local/bin/R", "/opt/R/bin/R"]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


class RKernel(QtCore.QObject):
    """One R session."""

    output = QtCore.Signal(str, str)  # text, kind: out|err|warning|echo|info
    message = QtCore.Signal(dict)  # any protocol message
    stateChanged = QtCore.Signal(str)  # starting|ready|busy|dead
    started = QtCore.Signal(dict)  # hello message
    finished = QtCore.Signal(int)
    promptChanged = QtCore.Signal(str)

    def __init__(self, shell_config, parent=None):
        super().__init__(parent)
        self.config = dict(shell_config)
        self.state = "dead"
        self.info = {}
        self.prompt = "> "
        self._proc = None
        self._server = None
        self._sock = None
        self._token = ""
        self._buf = b""
        self._got_hello = False
        self._queue = []  # pending EVAL requests (sent one at a time)
        self._request_id = 0
        self._callbacks = {}
        self._decoder_out = None
        self._expect_exit = False

    # ------------------------------------------------------------ lifecycle --
    def start(self):
        exe = find_r_executable(self.config.get("exe") or "R")
        if not exe:
            self.output.emit(
                f"Could not find the R executable '{self.config.get('exe')}'.\n"
                "Install R (https://cran.r-project.org) or set its path via "
                "Shell > Edit shell configurations.\n", "err")
            self._set_state("dead")
            return
        self._buf = b""
        self._got_hello = False
        self._queue = []
        self._callbacks = {}
        self._expect_exit = False
        self._token = secrets.token_hex(16)
        self._server = QtNetwork.QTcpServer(self)
        self._server.listen(QtNetwork.QHostAddress.LocalHost, 0)
        self._server.newConnection.connect(self._on_connection)

        self._proc = QtCore.QProcess(self)
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert("RYZO_PORT", str(self._server.serverPort()))
        env.insert("RYZO_TOKEN", self._token)
        if not env.contains("LANG") or env.value("LANG") in ("", "C", "POSIX"):
            env.insert("LANG", "C.UTF-8" if not sys.platform == "darwin" else "en_US.UTF-8")
        env.insert("R_CLI_NUM_COLORS", "1")
        env.insert("RSTUDIO", "")  # some packages check this; we're not RStudio
        for line in (self.config.get("env") or "").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                env.insert(k.strip(), v.strip())
        self._proc.setProcessEnvironment(env)
        start_dir = os.path.expanduser(self.config.get("startDir") or "")
        if start_dir and os.path.isdir(start_dir):
            self._proc.setWorkingDirectory(start_dir)
        elif not start_dir:
            self._proc.setWorkingDirectory(os.path.expanduser("~"))
        args = ["--no-echo", "--interactive", "--no-readline", "--quiet",
                "--no-save", "--no-restore"]
        if sys.platform.startswith("win"):
            # Rterm: --ess gives interactive behaviour on pipes without readline
            args = ["--ess", "--no-echo", "--quiet", "--no-save", "--no-restore"]
        try:
            args += shlex.split(self.config.get("args") or "")
        except ValueError:
            pass
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        self._set_state("starting")
        self._proc.start(exe, args)
        script = KERNEL_SCRIPT.replace("\\", "/")
        self._proc.write(f'source("{script}", encoding = "UTF-8")\n'.encode())

    def restart(self):
        self.terminate(wait=True)
        self.start()

    def terminate(self, wait=False):
        if self._proc is None:
            return
        proc = self._proc
        self._expect_exit = True
        if proc.state() != QtCore.QProcess.NotRunning:
            if self._sock is not None:
                self._sock.abort()
            proc.closeWriteChannel()
            proc.terminate()
            if wait and not proc.waitForFinished(1500):
                proc.kill()
                proc.waitForFinished(1000)
            elif not wait:
                QtCore.QTimer.singleShot(1500, lambda p=proc: p.state() != QtCore.QProcess.NotRunning and p.kill())
        if wait:
            self._cleanup()

    def _cleanup(self):
        if self._sock is not None:
            self._sock.deleteLater()
            self._sock = None
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
        self._set_state("dead")

    def interrupt(self):
        if self._proc is None or self._proc.state() == QtCore.QProcess.NotRunning:
            return
        self._queue = []
        pid = self._proc.processId()
        if sys.platform.startswith("win"):
            self.output.emit("[Interrupting is not supported on Windows; use Restart instead]\n", "info")
            return
        try:
            os.kill(pid, signal.SIGINT)
        except OSError as err:
            self.output.emit(f"[Could not interrupt: {err}]\n", "info")

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.stateChanged.emit(state)

    @property
    def is_alive(self):
        return self.state in ("ready", "busy")

    # ----------------------------------------------------------- transport --
    def _on_connection(self):
        sock = self._server.nextPendingConnection()
        if self._sock is not None:
            sock.abort()
            return
        sock.waitForReadyRead(3000)
        line = bytes(sock.readLine()).decode(errors="replace").strip()
        if line != self._token:
            sock.abort()
            return
        self._sock = sock
        self._server.close()

    def _send(self, header, lines=()):
        if self._sock is None:
            return False
        data = header + "\n" + "".join(line + "\n" for line in lines)
        self._sock.write(data.encode("utf-8"))
        self._sock.flush()
        return True

    def write_stdin(self, text):
        """Raw input for readline()/scan() while R is busy."""
        if self._proc is not None:
            self._proc.write(text.encode("utf-8"))

    def _on_stdout(self):
        self._buf += bytes(self._proc.readAllStandardOutput())
        self._process_buffer()

    def _process_buffer(self):
        buf = self._buf
        while buf:
            i = buf.find(FRAME_START)
            if i < 0:
                # keep a possible partial frame marker at the end
                keep = 0
                for k in range(1, len(FRAME_START)):
                    if buf.endswith(FRAME_START[:k]):
                        keep = k
                text, buf = (buf[:-keep], buf[-keep:]) if keep else (buf, b"")
                self._emit_text(text)
                break
            if i > 0:
                self._emit_text(buf[:i])
                buf = buf[i:]
            j = buf.find(FRAME_END)
            if j < 0:
                break  # incomplete frame
            payload = buf[len(FRAME_START):j]
            buf = buf[j + 1:]
            try:
                msg = json.loads(payload.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            self._handle(msg)
        self._buf = buf

    def _emit_text(self, data, kind="out"):
        if not data:
            return
        if not self._got_hello:
            return  # bootstrap echo
        text = data.decode("utf-8", errors="replace")
        self.output.emit(text, kind)

    def _on_stderr(self):
        data = bytes(self._proc.readAllStandardError())
        if data:
            self.output.emit(data.decode("utf-8", errors="replace"), "err")

    def _on_error(self, err):
        if err == QtCore.QProcess.FailedToStart:
            self.output.emit("Failed to start R. Check the executable in the shell configuration.\n", "err")
            self._cleanup()

    def _on_finished(self, code, status=None):
        if self._buf:
            self._process_buffer()
        if not self._expect_exit:
            self.output.emit(f"\n[R process exited with code {code}]\n", "info")
        self._cleanup()
        self.finished.emit(code)

    # ------------------------------------------------------------ messages --
    def _handle(self, msg):
        t = msg.get("type")
        if t == "hello":
            self._got_hello = True
            self.info = msg
            self.started.emit(msg)
        elif t == "ready":
            self.prompt = msg.get("prompt", "> ")
            self._set_state("ready")
            self.promptChanged.emit(self.prompt)
            self._send_next()
        elif t == "busy":
            self._set_state("busy")
        elif t == "stream":
            kind = {"stderr": "err", "warning": "warning"}.get(msg.get("name"), "out")
            self.output.emit(msg.get("text", ""), kind)
        elif t == "echo":
            self.output.emit(msg.get("text", ""), "echo")
        cb = None
        if "id" in msg and msg["id"] in self._callbacks:
            cb = self._callbacks.pop(msg["id"])
        if cb is not None:
            cb(msg)
        self.message.emit(msg)

    def _next_id(self, callback=None):
        self._request_id += 1
        rid = str(self._request_id)
        if callback is not None:
            self._callbacks[rid] = callback
        return rid

    def _send_next(self):
        if self.state != "ready" or not self._queue:
            return
        header, lines = self._queue.pop(0)
        if self._send(header, lines):
            self._set_state("busy")

    # ----------------------------------------------------------------- API --
    def execute(self, code, mode="line", srcname="", lineoffset=0):
        """Queue code for evaluation. mode: line, block or file."""
        lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        srcname = srcname.replace("\t", " ")
        self._queue.append((f"EVAL\t{mode}\t{len(lines)}\t{srcname}\t{int(lineoffset)}", lines))
        self._send_next()

    def request(self, header, lines=(), callback=None):
        """Introspection request; only sent when idle. Returns False otherwise."""
        if self.state != "ready":
            return False
        parts = header.split("\t")
        if callback is not None:
            rid = self._next_id(callback)
            parts.insert(1, rid)
        return self._send("\t".join(parts), lines)

    def complete(self, line, callback):
        return self.request("COMPLETE", [line], callback)

    def calltip(self, name, callback):
        return self.request(f"CALLTIP\t{name}", (), callback)

    def workspace(self, path=""):
        return self.request(f"WORKSPACE\t{path}")

    def help(self, topic, package=""):
        return self.request(f"HELP\t{topic}\t{package}")

    # plots: sizes are in screen pixels (96 dpi); dpr is the display's pixel ratio
    def set_plot_size(self, w, h, dpr=1.0):
        return self.request(f"PLOTSIZE\t{int(w)}\t{int(h)}\t{dpr:g}")

    def render_plot(self, plot_id, w, h, dpr=1.0):
        return self.request(f"RENDERPLOT\t{plot_id}\t{int(w)}\t{int(h)}\t{dpr:g}")

    def save_plot(self, plot_id, filename, w, h, dpi=96):
        return self.request(f"SAVEPLOT\t{plot_id}\t{filename}\t{w:g}\t{h:g}\t{dpi:g}")

    def remove_plot(self, plot_id="all"):
        return self.request(f"REMOVEPLOT\t{plot_id}")

    def set_plot_style(self, modern):
        return self.request(f"PLOTSTYLE\t{1 if modern else 0}")

    def setwd(self, path):
        return self.request(f"SETWD\t{path}")

    def query(self, code, callback):
        """Evaluate R code and pass its (JSON-converted) value to callback(msg)."""
        lines = code.split("\n")
        return self.request(f"QUERY\t{len(lines)}", lines, callback)

    def preview(self, code, callback):
        """Evaluate import code and pass a data preview to callback(msg)."""
        lines = code.split("\n")
        return self.request(f"PREVIEW\t{len(lines)}", lines, callback)

    def silent(self, code, callback=None):
        lines = code.split("\n")
        rid = self._next_id(callback)
        if self.state != "ready":
            return False
        return self._send(f"SILENT\t{len(lines)}\t{rid}", lines)
