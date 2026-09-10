"""Isolated downloader checks: synthetic HTTP data, no NCBI or shared storage."""
import hashlib
import http.server
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/pubmed/sync_pubmed.sh"
NAME = "pubmed26n1572.xml.gz"
BODY = b"synthetic compressed-file stand-in\n" * 100


@pytest.fixture
def runner(tmp_path):
    if any(not shutil.which(tool) for tool in ("bash", "wget", "timeout", "md5sum")):
        pytest.skip("downloader tests require Bash, wget, timeout and md5sum")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # macOS lacks util-linux flock. Use the same inherited-fd advisory lock;
    # Linux exercises the installed production flock command directly.
    if not shutil.which("flock"):
        shim = bindir / "flock"
        shim.write_text(
            f"#!{sys.executable}\nimport fcntl, sys\n"
            "try: fcntl.flock(int(sys.argv[-1]), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "except BlockingIOError: sys.exit(75)\n"
        )
        shim.chmod(0o755)
    data = tmp_path / "data"
    data.mkdir()
    (data / "lastest").write_text("1571\n")
    state = {"requests": [], "xml_count": 0, "mode": "ok", "entered": threading.Event(),
             "indices": [1572], "fail_name": None}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            name = self.path.lstrip("/")
            state["requests"].append((name, self.headers.get("Range")))
            mode = state["mode"]
            if not name:
                if mode == "listing_failure":
                    self.send_error(503)
                    return
                body = "\n".join(
                    f'<a href="pubmed26n{i}.xml.gz">pubmed26n{i}.xml.gz</a> 2026-09-10'
                    for i in state["indices"]
                ).encode()
                if mode == "bad_listing":
                    body = b"<html>upstream maintenance</html>"
            elif name == state["fail_name"]:
                self.send_error(503)
                return
            elif name.endswith(".md5"):
                digest = hashlib.md5(BODY).hexdigest()
                target = "../elsewhere" if mode == "wrong_name" else name.removesuffix(".md5")
                body = f"MD5({target})= {digest}\n".encode()
                if mode == "gnu_md5":
                    body = f"{digest}  {target}\n".encode()
                if mode == "bad_md5":
                    body = b"<html>error</html>"
                if mode == "missing_md5":
                    self.send_error(404)
                    return
            elif name.endswith("_stats.html"):
                if mode == "stats_failure":
                    self.send_error(503)
                    return
                body = b"synthetic stats"
            else:
                state["xml_count"] += 1
                if mode == "new_publication":
                    state["indices"] = [1572, 1573]
                state["entered"].set()
                if mode == "network_failure":
                    self.send_error(503)
                    return
                if mode in ("slow", "locked"):
                    time.sleep(2)
                body = BODY
                if mode == "corrupt_once" and state["xml_count"] == 1:
                    body = b"x" * len(BODY)
                if mode == "interrupted_once" and state["xml_count"] == 1:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(BODY)))
                    self.end_headers()
                    self.wfile.write(body[:100])
                    self.wfile.flush()
                    self.close_connection = True
                    return
            offset = 0
            if self.headers.get("Range"):
                offset = int(self.headers["Range"].split("=")[1].split("-")[0])
            self.send_response(206 if offset else 200)
            if offset:
                self.send_header("Content-Range", f"bytes {offset}-{len(body)-1}/{len(body)}")
            self.send_header("Content-Length", str(len(body) - offset))
            self.end_headers()
            try:
                self.wfile.write(body[offset:])
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = dict(os.environ, BASE_DIR=str(data),
               URL_PREFIX=f"http://127.0.0.1:{server.server_port}",
               MAX_RETRIES="2", RETRY_DELAY="0", IO_TIMEOUT="5", DOWNLOAD_TIMEOUT="5",
               PATH=f"{bindir}:{os.environ['PATH']}", no_proxy="127.0.0.1", NO_PROXY="127.0.0.1")

    def run(mode="ok", **overrides):
        state["mode"] = mode
        return subprocess.run([shutil.which("bash"), str(SCRIPT)],
                              env=dict(env, **overrides), capture_output=True, text=True,
                              errors="replace", timeout=15)

    yield run, data, state, env
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize("mode", ["ok", "gnu_md5", "corrupt_once", "interrupted_once", "stats_failure"])
def test_success_and_recovery(runner, mode):
    run, data, state, _ = runner
    result = run(mode)
    assert result.returncode == 0, result.stderr
    assert (data / "lastest").read_text() == "1572\n"
    assert (data / NAME).read_bytes() == BODY
    assert not (data / (NAME + ".part")).exists()
    assert not any("1573" in path for path, _ in state["requests"])
    if mode == "interrupted_once":
        assert (NAME, "bytes=100-") in state["requests"]
    if mode == "corrupt_once":
        assert state["xml_count"] == 2
        assert all(r is None for path, r in state["requests"] if path == NAME)
    if mode == "stats_failure":
        assert "统计 HTML 未取得" in (data / "sync.log").read_text()


@pytest.mark.parametrize("mode", ["network_failure", "missing_md5", "bad_md5", "wrong_name", "slow"])
def test_failure_preserves_progress_and_existing_file(runner, mode):
    run, data, state, _ = runner
    (data / NAME).write_bytes(b"previous unverified file")
    result = run(mode, DOWNLOAD_TIMEOUT="1", MAX_RETRIES="1")
    assert result.returncode != 0
    assert (data / "lastest").read_text() == "1571\n"
    assert (data / NAME).read_bytes() == b"previous unverified file"
    log = (data / "sync.log").read_text()
    assert "lastest 保持 1571" in log
    if mode == "slow":
        assert "退出码=124" in log
    if mode in ("network_failure", "missing_md5"):
        assert "退出码=8" in log
    if mode in ("bad_md5", "wrong_name", "missing_md5"):
        assert state["xml_count"] == 0


def test_reuse_verified_file_after_interrupted_state_update(runner):
    run, data, state, _ = runner
    (data / NAME).write_bytes(BODY)
    assert run().returncode == 0
    assert state["xml_count"] == 0
    assert (data / "lastest").read_text() == "1572\n"


@pytest.mark.parametrize("index", ["", "oops", "-1", "1571\n1572"])
def test_invalid_state_stops_before_network(runner, index):
    run, data, state, _ = runner
    (data / "lastest").write_text(index)
    assert run().returncode != 0
    assert state["requests"] == []
    assert (data / "lastest").read_text() == index


def test_lock_excludes_second_process_and_releases_after_exit(runner):
    run, data, state, env = runner
    state["mode"] = "locked"
    first = subprocess.Popen([shutil.which("bash"), str(SCRIPT)], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert state["entered"].wait(5)
        second = run("locked")
        assert second.returncode == 75
        first.communicate(timeout=10)
        assert first.returncode == 0
        assert state["xml_count"] == 1
        (data / "lastest").write_text("1571\n")
        assert run().returncode == 0
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate()


def test_resume_in_next_invocation_after_retry_budget_exhausted(runner):
    run, data, state, _ = runner
    assert run("interrupted_once", MAX_RETRIES="1").returncode == 1
    assert (data / "lastest").read_text() == "1571\n"
    assert (data / (NAME + ".part")).read_bytes() == BODY[:100]
    assert not (data / NAME).exists()
    assert run("interrupted_once").returncode == 0
    assert (NAME, "bytes=100-") in state["requests"]
    assert (data / NAME).read_bytes() == BODY


def test_missing_state_stops_before_network(runner):
    run, data, state, _ = runner
    (data / "lastest").unlink()
    assert run().returncode != 0
    assert state["requests"] == []
    assert "无法读取 lastest" in (data / "sync.log").read_text()


def test_multiple_same_day_files_sorted_and_deduplicated(runner):
    run, data, state, _ = runner
    state["indices"] = [1574, 1572, 1573, 1572]
    assert run().returncode == 0
    assert (data / "lastest").read_text() == "1574\n"
    assert [n for n, _ in state["requests"] if n.endswith(".xml.gz")] == [
        f"pubmed26n{i}.xml.gz" for i in (1572, 1573, 1574)]
    assert not list(data.glob(".sync_pubmed.list.*"))


def test_middle_failure_stops_then_next_run_recovers(runner):
    run, data, state, _ = runner
    state["indices"] = [1572, 1573, 1574]
    state["fail_name"] = "pubmed26n1573.xml.gz"
    assert run().returncode == 1
    assert (data / "lastest").read_text() == "1572\n"
    assert not any("1574" in n for n, _ in state["requests"])
    state["requests"].clear()
    state["fail_name"] = None
    assert run().returncode == 0
    assert (data / "lastest").read_text() == "1574\n"
    assert not any("1572" in n for n, _ in state["requests"])


def test_already_current_does_not_request_unpublished_file(runner):
    run, data, state, _ = runner
    state["indices"] = [1571]
    assert run().returncode == 0
    assert state["requests"] == [("", None)]
    assert "本轮已追平" in (data / "sync.log").read_text()


@pytest.mark.parametrize("mode", ["listing_failure", "bad_listing"])
def test_unusable_directory_is_failure_not_up_to_date(runner, mode):
    run, data, state, _ = runner
    assert run(mode).returncode == 1
    assert (data / "lastest").read_text() == "1571\n"
    assert state["xml_count"] == 0
    assert not list(data.glob(".sync_pubmed.list.*"))


def test_gap_in_directory_never_skips_id(runner):
    run, data, state, _ = runner
    state["indices"] = [1572, 1574]
    assert run().returncode == 1
    assert (data / "lastest").read_text() == "1572\n"
    assert not any("1574" in n for n, _ in state["requests"])


def test_snapshot_does_not_expand_during_run(runner):
    run, data, state, _ = runner
    assert run("new_publication").returncode == 0
    assert (data / "lastest").read_text() == "1572\n"
    assert state["indices"] == [1572, 1573]
    assert not any("1573" in n for n, _ in state["requests"])
    assert run().returncode == 0
    assert (data / "lastest").read_text() == "1573\n"


def test_local_ahead_of_directory_is_reported(runner):
    run, data, state, _ = runner
    state["indices"] = [1570]
    assert run().returncode == 1
    assert (data / "lastest").read_text() == "1571\n"
    assert state["xml_count"] == 0
