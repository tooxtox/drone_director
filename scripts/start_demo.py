#!/usr/bin/env python3
"""Start the local city demo, supervise its processes and open the browser."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
RUNTIME = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
OPENER = build_opener(ProxyHandler({}))  # Local readiness checks never use HTTP_PROXY.
PROBE = "import fastapi,uvicorn,pydantic_settings,numpy,networkx,websockets,yaml,dotenv"


class LaunchError(RuntimeError):
    pass


def request(url: str) -> str | None:
    try:
        with OPENER.open(url, timeout=1) as response:
            return response.read(2_000_000).decode("utf-8")
    except (URLError, OSError, UnicodeError):
        return None


def healthy(url: str) -> bool:
    try:
        data = json.loads(request(url + "/api/health") or "null")
        return isinstance(data, dict) and data.get("status") == "ok" and "version" in data and "time" in data
    except (ValueError, TypeError):
        return False


def ours(url: str, frontend: bool = False) -> bool:
    if not healthy(url):
        return False
    if frontend:
        return "天枢智航" in (request(url) or "")
    try:
        spec = json.loads(request(url + "/openapi.json") or "{}")
        return "天枢智航" in spec.get("info", {}).get("title", "")
    except (ValueError, AttributeError):
        return False


def available(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def run(command: list[str], *, env: dict[str, str] | None = None, cwd: Path = ROOT) -> None:
    if subprocess.run(command, cwd=cwd, env=env).returncode:
        raise LaunchError("依赖准备失败，请检查上方错误和网络连接后重新启动。")


def python_works(path: str, backend: bool = False) -> bool:
    code = "import sys; assert sys.version_info >= (3,12)"
    if backend:
        code += ";" + PROBE
    try:
        return subprocess.run([path, "-c", code], cwd=ROOT, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def find_python() -> str:
    executable = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    candidates = [str(ROOT / name / executable) for name in (".venv-demo", ".venv-runtime", ".venv")]
    candidates += [sys.executable, shutil.which("python3.12") or "", shutil.which("python3") or "",
                   str(RUNTIME / "python/bin/python3")]
    valid = [path for path in dict.fromkeys(candidates) if path and Path(path).is_file() and python_works(path)]
    for path in valid:
        if python_works(path, backend=True):
            return path

    print("首次启动：正在准备 Python 后端依赖…", flush=True)
    virtualenv = ROOT / ".venv-demo"
    uv = shutil.which("uv")
    if uv:
        env = os.environ.copy()
        env["UV_PROJECT_ENVIRONMENT"] = str(virtualenv)
        run([uv, "sync", "--locked", "--no-dev", "--python", valid[0] if valid else "3.12"], env=env)
    else:
        if not valid:
            raise LaunchError("请先安装 Python 3.12+（或 uv），然后重新启动。")
        run([valid[0], "-m", "venv", str(virtualenv)])
        python = str(virtualenv / executable)
        # Read dependencies using the selected Python 3.12, even if this launcher runs on 3.10.
        code = "import json,tomllib; print(json.dumps(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))"
        dependencies = json.loads(subprocess.check_output([python, "-c", code], cwd=ROOT, text=True))
        run([python, "-m", "pip", "install", *dependencies])
    python = str(virtualenv / executable)
    if not python_works(python, backend=True):
        raise LaunchError("后端环境校验失败，请检查 Python 依赖安装结果。")
    return python


def find_node() -> str:
    candidates = [shutil.which("node"), str(RUNTIME / "node/bin/node")]
    for path in candidates:
        if not path or not Path(path).is_file():
            continue
        try:
            version = subprocess.check_output([path, "--version"], text=True).strip().lstrip("v")
            major, minor = map(int, version.split(".")[:2])
            if major > 22 or major == 22 and minor >= 12:
                return path
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
    raise LaunchError("请先安装 Node.js 22.12+（包含 npm），然后重新启动。")


def prepare_frontend(node: str) -> None:
    env = os.environ.copy()
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    probe = "import('vite').then(()=>import('vue')).then(()=>import('three')).catch(()=>process.exit(1))"
    if subprocess.run([node, "--input-type=module", "-e", probe], cwd=FRONTEND,
                      env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        return
    print("首次启动：正在安装前端依赖…", flush=True)
    npm = shutil.which("npm", path=env["PATH"])
    cli_candidates = [Path(node).parent / "node_modules/npm/bin/npm-cli.js",
                      Path(node).parent.parent / "lib/node_modules/npm/bin/npm-cli.js",
                      Path("/usr/share/nodejs/npm/bin/npm-cli.js")]
    if npm:
        cli_candidates.insert(0, Path(npm).resolve().parent / "node_modules/npm/bin/npm-cli.js")
        cli_candidates.insert(0, Path(npm).resolve().parent / "npm-cli.js")
    cli = next((p for p in cli_candidates if p.is_file()), None)
    if cli:
        run([node, str(cli), "ci", "--no-audit", "--no-fund"], env=env, cwd=FRONTEND)
    elif npm and os.name != "nt":
        run([npm, "ci", "--no-audit", "--no-fund"], env=env, cwd=FRONTEND)
    else:
        raise LaunchError("未找到 npm。请安装包含 npm 的 Node.js，执行 npm --prefix frontend ci 后重试。")


def start(command: list[str], cwd: Path, env: dict[str, str], log: Path) -> subprocess.Popen:
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with log.open("w", encoding="utf-8") as output:
        return subprocess.Popen(command, cwd=cwd, env=env, stdout=output,
                                stderr=subprocess.STDOUT, **options)


def wait_ready(url: str, process: subprocess.Popen, log: Path, *, frontend: bool = False) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        if ours(url, frontend=frontend):
            return
        time.sleep(.3)
    tail = log.read_text(encoding="utf-8", errors="replace")[-3000:]
    raise LaunchError(f"服务未能就绪：{url}\n日志：{log}\n{tail}")


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)


def open_browser(url: str, disabled: bool) -> None:
    print(f"演示地址：{url}", flush=True)
    if not disabled:
        try:
            if not webbrowser.open(url):
                print("浏览器未自动打开，请手动访问上面的地址。", flush=True)
        except webbrowser.Error:
            print("请手动打开上面的演示地址。", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="一键启动天枢智航城市无人机演示")
    parser.add_argument("--backend-port", type=int, default=8011)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--no-browser", action="store_true", help="启动服务，但不自动打开浏览器")
    args = parser.parse_args()
    if not all(1 <= p <= 65535 for p in (args.backend_port, args.frontend_port)) or args.backend_port == args.frontend_port:
        parser.error("端口须为 1–65535 的不同整数")
    backend = f"http://127.0.0.1:{args.backend_port}"
    frontend = f"http://127.0.0.1:{args.frontend_port}"
    children: list[subprocess.Popen] = []
    try:
        if not available(args.frontend_port):
            if ours(frontend, frontend=True):
                print("已有演示正在运行，直接打开现有页面。", flush=True)
                open_browser(frontend, args.no_browser)
                return 0
            raise LaunchError(f"前端端口 {args.frontend_port} 已被占用。请使用 --frontend-port 指定其他端口。")
        reuse_backend = not available(args.backend_port)
        if reuse_backend and not ours(backend):
            raise LaunchError(f"后端端口 {args.backend_port} 已被占用。请使用 --backend-port 指定其他端口。")
        node = find_node()
        prepare_frontend(node)
        python = None if reuse_backend else find_python()
        logs = ROOT / "data/logs"
        logs.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(TS_HOST="127.0.0.1", TS_PORT=str(args.backend_port), TS_API_TARGET=backend, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        if python:
            log = logs / f"demo-backend-{args.backend_port}.log"
            process = start([python, "-X", "utf8", "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", str(args.backend_port)], ROOT, env, log)
            children.append(process)
            wait_ready(backend, process, log)
        else:
            print(f"复用已有后端：{backend}", flush=True)
        log = logs / f"demo-frontend-{args.frontend_port}.log"
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        process = start([node, str(FRONTEND / "node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", str(args.frontend_port)], FRONTEND, env, log)
        children.append(process)
        wait_ready(frontend, process, log, frontend=True)
        open_browser(frontend, args.no_browser)
        print("点击“创建 100 机演示”，然后“启动仿真”。\n按 Ctrl+C 退出；只停止本脚本启动的服务。", flush=True)
        while True:
            for child in children:
                if child.poll() is not None:
                    raise LaunchError(f"服务意外退出，请查看 {logs} 下的日志。")
            time.sleep(.5)
    except KeyboardInterrupt:
        print("\n正在停止演示服务…", flush=True)
        return 0
    except (LaunchError, OSError, subprocess.SubprocessError) as error:
        print(f"启动失败：{error}", file=sys.stderr, flush=True)
        return 1
    finally:
        for child in reversed(children):
            stop(child)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
