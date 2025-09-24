# 🚀 Multi-Emulator Runner for Android AVDs  

This Python script automates running multiple Android emulators in parallel with controlled concurrency. It handles cloning base AVDs, boot checks, port allocation, CPI link automation, APK installation, and app launching — all with logging and runtime control.  

---

## ✨ Features
- Automatic **AVD cloning** (from a base emulator).  
- Run multiple emulators with **concurrency limits**.  
- **Port management** to avoid conflicts.  
- Waits until emulator is fully **booted & ready**.  
- Automates **CPI link open → APK install → app launch**.  
- Saves emulator logs in `./emulator_logs/`.  
- Option to **keep emulators running** or kill them after tasks.  

---

## ⚙️ Configuration
Edit the **config section** at the top of the script:

| Variable          | Description |
|-------------------|-------------|
| `BASE_AVD`        | Name of the base AVD to clone |
| `APK_PATH`        | Path to the APK file to install |
| `PACKAGE_NAME`    | App package name to launch |
| `RUN_TIME`        | Seconds to keep the app running |
| `BOOT_TIMEOUT`    | Max wait time for emulator boot |
| `CONCURRENT_LIMIT`| Number of emulators to run in parallel |
| `KEEP_EMULATORS`  | Leave emulators running (`True`) or kill after use |

---

## 🛠️ Requirements
- Python **3.7+**  
- Android SDK installed with:
  - `emulator`  
  - `adb`  
- At least one working **base AVD** (`BASE_AVD`)  

📌 Python dependencies: none (standard library only). See [`requirements.txt`](./requirements.txt).  

---

## ▶️ Usage
```bash
python3 multi_emulator_runner.py
