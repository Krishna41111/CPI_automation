#!/usr/bin/env python3
"""
Robust multi-emulator runner:
- clones BASE_AVD into fresh copies,
- starts each emulator with a reserved port,
- waits until adb device appears and sys.boot_completed=1,
- opens CPI link with random userId, waits, installs APK, opens app for RUN_TIME,
- keeps emulators running by default (no auto-kill).
"""

import os
import sys
import time
import shutil
import random
import threading
import subprocess
from pathlib import Path

# ---------- CONFIG ----------
BASE_AVD = "MyAVD3"   # AVD to clone (must exist)
APK_PATH = r"C:\ac\grab-5-367-200.apk"
PACKAGE_NAME = "com.grabtaxi.passenger"
RUN_TIME = 180                # seconds app should run
BOOT_TIMEOUT = 420            # seconds to wait for boot
CONCURRENT_LIMIT = 2          # max instances in parallel (change here)
KEEP_EMULATORS = True         # if False, script will attempt to kill emulators it started
LOG_DIR = Path("./emulator_logs")
BASE_URL = "https://adswedmedia.com/redirect/manual-offer/1131/user/{userId}/site/Hh1Gk5"
AVD_DIR = Path(os.path.expanduser("~")) / ".android" / "avd"
# -----------------------------

LOG_DIR.mkdir(parents=True, exist_ok=True)


def run_cmd(cmd, timeout=None, capture_output=False):
    return subprocess.run(cmd, check=False, capture_output=capture_output, text=True, timeout=timeout)


def list_adb_devices():
    """Return set of adb serials in 'device' state."""
    try:
        r = run_cmd(["adb", "devices"], capture_output=True)
    except Exception:
        return set()
    out = r.stdout or ""
    lines = out.strip().splitlines()
    devs = set()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devs.add(parts[0])
    return devs


def find_free_emulator_port(occupied_serials):
    """Find an even console port (5554..5682) whose emulator-<port> is not in occupied_serials."""
    for port in range(5554, 5684, 2):
        serial = f"emulator-{port}"
        if serial not in occupied_serials:
            return port
    raise RuntimeError("No free emulator ports available")


def fresh_clone_avd(new_name: str):
    """Delete any existing copy and clone BASE_AVD -> new_name; update .ini & config.ini paths/names."""
    base_avd_dir = AVD_DIR / f"{BASE_AVD}.avd"
    base_ini = AVD_DIR / f"{BASE_AVD}.ini"
    new_avd_dir = AVD_DIR / f"{new_name}.avd"
    new_ini = AVD_DIR / f"{new_name}.ini"

    if not base_avd_dir.exists() or not base_ini.exists():
        raise FileNotFoundError(f"Base AVD '{BASE_AVD}' not found in {AVD_DIR}")

    # Remove any old clone
    if new_avd_dir.exists():
        shutil.rmtree(new_avd_dir, ignore_errors=True)
    if new_ini.exists():
        try:
            new_ini.unlink()
        except Exception:
            pass

    shutil.copytree(base_avd_dir, new_avd_dir)
    shutil.copy2(base_ini, new_ini)

    # Update new .ini path entry
    ini_lines = []
    with open(new_ini, "r", encoding="utf-8") as f:
        ini_lines = f.readlines()
    with open(new_ini, "w", encoding="utf-8") as f:
        for line in ini_lines:
            if line.startswith("path="):
                f.write(f"path={str(new_avd_dir)}\n")
            else:
                # also replace any occurrences of BASE_AVD in other lines
                f.write(line.replace(BASE_AVD, new_name))
    # Update config.ini inside .avd
    conf_file = new_avd_dir / "config.ini"
    if conf_file.exists():
        with open(conf_file, "r", encoding="utf-8") as f:
            cfg_lines = f.readlines()
        found_id = False
        found_name = False
        with open(conf_file, "w", encoding="utf-8") as f:
            for line in cfg_lines:
                if line.startswith("avd.id="):
                    f.write(f"avd.id={new_name}\n")
                    found_id = True
                elif line.startswith("avd.name="):
                    f.write(f"avd.name={new_name}\n")
                    found_name = True
                else:
                    f.write(line.replace(BASE_AVD, new_name))
            if not found_id:
                f.write(f"\navd.id={new_name}\n")
            if not found_name:
                f.write(f"avd.name={new_name}\n")
    print(f"[clone] {BASE_AVD} → {new_name} (fresh) done.")


def start_emulator_detached(avd_name: str, port: int):
    """Start emulator and return Popen object. Output goes to log file (avoids PIPE blocking)."""
    logfile = LOG_DIR / f"{avd_name}.log"
    cmd = ["emulator", "-avd", avd_name, "-port", str(port), "-no-snapshot-load"]
    # NOTE: you can add flags like -wipe-data, -no-window, -no-audio for CI/headless runs.
    print(f"[start] {avd_name} port={port} -> {cmd}")
    lf = open(logfile, "ab")
    proc = subprocess.Popen(cmd, stdout=lf, stderr=lf, stdin=subprocess.DEVNULL, close_fds=True)
    return proc, logfile


def wait_for_serial(serial: str, timeout: int = BOOT_TIMEOUT):
    """Wait until adb devices reports serial."""
    start = time.time()
    while time.time() - start < timeout:
        devs = list_adb_devices()
        if serial in devs:
            return True
        time.sleep(2)
    raise TimeoutError(f"{serial} did not appear in adb devices within {timeout}s")


def wait_for_boot_complete(serial: str, timeout: int = BOOT_TIMEOUT):
    """Wait until sys.boot_completed == 1"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = run_cmd(["adb", "-s", serial, "shell", "getprop", "sys.boot_completed"], capture_output=True)
            if r.stdout and r.stdout.strip() == "1":
                print(f"[boot] {serial} boot complete.")
                return True
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"{serial} did not finish boot within {timeout}s")


def open_cpi_and_install(serial: str, apk_path: str, package_name: str, run_time: int):
    """Perform CPI link open -> wait 30s -> install apk -> wait 10s -> open app -> wait run_time."""
    # random user id
    user_id = random.randint(100000, 200000)
    url = BASE_URL.replace("{userId}", str(user_id))
    print(f"[task] {serial} opening CPI link: {url}")
    run_cmd(["adb", "-s", serial, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url])
    time.sleep(30)

    print(f"[task] {serial} installing APK: {apk_path}")
    r = run_cmd(["adb", "-s", serial, "install", "-r", apk_path], capture_output=True)
    print(f"[adb install] {serial} stdout: {r.stdout}; stderr: {r.stderr}")
    time.sleep(10)

    print(f"[task] {serial} launching app {package_name}")
    run_cmd(["adb", "-s", serial, "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"])
    print(f"[task] {serial} keeping app open for {run_time}s")
    time.sleep(run_time)
    print(f"[task] {serial} finished workflow.")


def instance_worker(avd_name: str, port: int, proc_holder: dict, semaphore: threading.Semaphore):
    """Thread target: start emulator (if not started), wait for its serial/boot and run the task."""
    acquired = False
    try:
        semaphore.acquire()
        acquired = True
        proc, logfile = start_emulator_detached(avd_name, port)
        proc_holder['proc'] = proc
        proc_holder['log'] = logfile

        serial = f"emulator-{port}"
        print(f"[worker] Waiting for serial {serial} to appear.")
        wait_for_serial(serial)
        print(f"[worker] {serial} present - waiting for boot.")
        wait_for_boot_complete(serial)

        # perform main workflow
        open_cpi_and_install(serial, APK_PATH, PACKAGE_NAME, RUN_TIME)

    except Exception as e:
        print(f"[ERROR] instance {avd_name} (port {port}) failed: {e}")
    finally:
        if acquired:
            semaphore.release()


def main():
    try:
        total = int(input("How many instances to run (total): ").strip() or "1")
    except Exception:
        print("Invalid number.")
        sys.exit(1)
    if total < 1:
        print("At least 1 instance required.")
        sys.exit(1)

    # Create list of clone names
    avd_names = [f"{BASE_AVD}_copy{i+1}" for i in range(total)]

    print("[step] Preparing clones...")
    for name in avd_names:
        fresh_clone_avd(name)

    # Reserve ports (deterministic) before launching to avoid race
    existing = list_adb_devices()
    reserved_ports = []
    for _ in avd_names:
        port = find_free_emulator_port(existing.union({f"emulator-{p}" for p in reserved_ports}))
        reserved_ports.append(port)

    # Start worker threads with concurrency limit
    sem = threading.Semaphore(CONCURRENT_LIMIT)
    threads = []
    procs_info = []
    for name, port in zip(avd_names, reserved_ports):
        proc_holder = {}
        procs_info.append((name, port, proc_holder))
        t = threading.Thread(target=instance_worker, args=(name, port, proc_holder, sem), daemon=False)
        t.start()
        threads.append(t)
        # small stagger to reduce instant pressure
        time.sleep(1)

    # Wait for all to finish
    for t in threads:
        t.join()

    print("All instance threads finished.")
    if KEEP_EMULATORS:
        print("Emulators were left running. To clean up later, use 'adb -s emulator-<port> emu kill' or delete clones.")
    else:
        print("Attempting to terminate emulators we started...")
        for name, port, info in procs_info:
            proc = info.get('proc')
            if proc and proc.poll() is None:
                try:
                    # prefer adb emu kill
                    serial = f"emulator-{port}"
                    run_cmd(["adb", "-s", serial, "emu", "kill"])
                except Exception:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
    print("Script complete.")


if __name__ == "__main__":
    main()
