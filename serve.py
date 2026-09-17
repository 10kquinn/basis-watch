"""Supervise the website and optional paper recorder in one container."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def commands(config):
    result = [[sys.executable, "-m", "streamlit", "run", "app.py",
               "--server.address=0.0.0.0", "--server.port=" + config.get("PORT", "8501"),
               "--server.fileWatcherType=none"]]
    if config.get("RECORDER_ENABLED") == "1":
        interval = int(config.get("RECORDER_INTERVAL", "900"))
        if interval < 60:
            raise ValueError("RECORDER_INTERVAL must be at least 60 seconds")
        result.append([sys.executable, "recorder.py", "--interval", str(interval)])
    return result


def prepare_storage(config):
    if config.get("RAILWAY_PROJECT_ID") and not config.get("SUPABASE_URL"):
        mount = config.get("RAILWAY_VOLUME_MOUNT_PATH")
        if not mount:
            raise ValueError("Attach a persistent Railway volume before starting the ledger")
        path = Path(config.get("LEDGER_DB_PATH", "/app/data/basis-watch.sqlite3")).resolve()
        if Path(mount).resolve() not in path.parents:
            raise ValueError("LEDGER_DB_PATH must be inside the persistent volume")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Railway mounts volumes as root. Only initialize the data directory;
        # the app and recorder themselves always run without root privileges.
        if os.getuid() == 0:
            os.chown(path.parent, 10001, 10001)
    if os.getuid() == 0:
        import pwd
        account = pwd.getpwuid(10001)
        os.initgroups(account.pw_name, account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
        # Match the unprivileged account so libraries do not access /root.
        os.environ["HOME"] = account.pw_dir


def supervise(child_commands):
    children = []
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for command in child_commands:
            children.append(subprocess.Popen(command))
        while not stopping:
            for child in children:
                if child.poll() is not None:
                    print("A service process exited; restarting the whole service.", flush=True)
                    return 1
            time.sleep(0.5)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 10
        for child in children:
            try:
                child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    child_commands = commands(os.environ)
    prepare_storage(os.environ)
    raise SystemExit(supervise(child_commands))
