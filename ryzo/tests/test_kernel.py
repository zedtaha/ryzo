"""Tests for the R kernel protocol, using the real Qt kernel class (headless)."""

import os
import shutil
import time

import pytest

pytestmark = pytest.mark.skipif(shutil.which("R") is None, reason="R is not installed")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6 import QtWidgets
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture()
def kernel(app):
    from ryzo.core.kernel import RKernel
    k = RKernel({"name": "R", "exe": "R"})
    k.out = []
    k.msgs = []
    k.output.connect(lambda text, kind: k.out.append((kind, text)))
    k.message.connect(k.msgs.append)
    k.start()
    wait(app, lambda: k.state == "ready", 30)
    yield k
    k.terminate(wait=True)


def wait(app, cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    raise TimeoutError("condition not met")


def run(app, k, code, mode="line"):
    k.out.clear()
    k.msgs.clear()
    k.execute(code, mode)
    wait(app, lambda: any(m["type"] == "ready" for m in k.msgs))
    return "".join(t for _, t in k.out)


def test_eval_and_print(app, kernel):
    assert "[1] 6" in run(app, kernel, "sum(1:3)")


def test_continuation_prompt(app, kernel):
    run(app, kernel, "g <- function(x) {")
    assert kernel.prompt == "+ "
    run(app, kernel, "x + 1 }")
    assert kernel.prompt == "> "
    assert "[1] 3" in run(app, kernel, "g(2)")


def test_errors_and_warnings(app, kernel):
    out = run(app, kernel, "stop('bad thing')")
    assert ("err", "Error: bad thing\n") in kernel.out
    out = run(app, kernel, "as.integer('x')")
    assert "NAs introduced by coercion" in out
    assert any(kind == "warning" for kind, _ in kernel.out)


def test_block_echo(app, kernel):
    out = run(app, kernel, "a <- 1\na + 1", mode="block")
    assert "> a <- 1" in out and "> a + 1" in out and "[1] 2" in out


def test_plot_message(app, kernel):
    run(app, kernel, "plot(1:10)\nabline(h = 5)", mode="block")
    plots = [m for m in kernel.msgs if m["type"] == "plot"]
    assert len(plots) == 1 and os.path.exists(plots[0]["path"])


def test_plot_rerender_and_export(app, kernel, tmp_path):
    kernel.set_plot_size(500, 400, 2)
    run(app, kernel, "hist(rnorm(50))\nplot(1:3)", mode="block")
    plots = [m for m in kernel.msgs if m["type"] == "plot"]
    assert [p["id"] for p in plots] == [1, 2] or len({p["id"] for p in plots}) == 2
    first = plots[0]
    assert first["width"] == 500 and first["dpr"] == 2
    kernel.msgs.clear()
    kernel.render_plot(first["id"], 300, 200, 1)
    wait(app, lambda: any(m["type"] == "plot" for m in kernel.msgs))
    again = [m for m in kernel.msgs if m["type"] == "plot"][0]
    assert again["id"] == first["id"] and again["rerender"] and again["width"] == 300
    for ext in ("pdf", "svg", "png", "tiff"):
        out = str(tmp_path / f"p.{ext}").replace("\\", "/")
        kernel.msgs.clear()
        kernel.save_plot(first["id"], out, 480, 360, 150)
        wait(app, lambda: any(m["type"] == "saved" for m in kernel.msgs))
        assert [m for m in kernel.msgs if m["type"] == "saved"][0]["ok"]
        assert os.path.getsize(out) > 1000


def test_introspection(app, kernel):
    run(app, kernel, "df <- data.frame(alpha = 1:3, beta = letters[1:3])")
    got = {}
    kernel.complete("df$al", lambda m: got.update(complete=m))
    wait(app, lambda: "complete" in got)
    assert "df$alpha" in got["complete"]["items"]
    kernel.calltip("paste", lambda m: got.update(calltip=m))
    wait(app, lambda: "calltip" in got)
    assert got["calltip"]["tip"].startswith("paste(")
    kernel.msgs.clear()
    kernel.workspace("")
    wait(app, lambda: any(m["type"] == "workspace" for m in kernel.msgs))
    ws = [m for m in kernel.msgs if m["type"] == "workspace"][0]
    entry = [e for e in ws["entries"] if e["name"] == "df"][0]
    assert entry["class"] == "data.frame" and entry["size"] == "3 x 2"


def test_interrupt(app, kernel):
    kernel.msgs.clear()
    kernel.execute("Sys.sleep(30)")
    wait(app, lambda: kernel.state == "busy")
    time.sleep(0.3)
    kernel.interrupt()
    wait(app, lambda: kernel.state == "ready", 10)
    assert "[1] 2" in run(app, kernel, "1 + 1")


def test_small_panel_does_not_break_plots(app, kernel):
    # A tiny Plots panel used to give "figure margins too large"
    kernel.set_plot_size(120, 60, 1)
    out = run(app, kernel, "plot(1:100)\nfit <- lm(dist ~ speed, cars)\nplot(fit)", mode="block")
    assert "margins too large" not in out
    plots = [m for m in kernel.msgs if m["type"] == "plot"]
    assert len({p["id"] for p in plots}) == 5  # plot(1:100) + 4 diagnostic plots
