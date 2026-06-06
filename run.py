# run.py
import json
import time
import argparse
import signal
from datetime import datetime
from pathlib import Path
import bot

_sigusr1_received = False

def _sigusr1_handler(signum, frame):
    global _sigusr1_received
    _sigusr1_received = True
    # time.sleep() is interrupted automatically when a signal handler runs on Unix

signal.signal(signal.SIGUSR1, _sigusr1_handler)


def _has_open_position(state_path: Path) -> bool:
    try:
        s = json.loads(state_path.read_text(encoding="utf-8"))
        return bool(s.get("open_pos"))
    except Exception:
        return False


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=int, default=300, help="実行間隔（秒）例: 300=5分, 600=10分")
    p.add_argument("--fast-interval", type=int, default=60, help="ポジション保有中の高速チェック間隔（秒）")
    p.add_argument("--print-tick", action="store_true", help="毎回tick時刻を表示する")
    return p.parse_args()

def main():
    args = parse_args()
    state_path = Path(__file__).parent / "state.json"
    print(f"[RUNNER] interval={args.interval}s fast_interval={args.fast_interval}s で bot.main() を実行します。Ctrl+Cで停止。")

    while True:
        if args.print_tick:
            now = datetime.now()
            print(f"[RUNNER] tick: {now.strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            bot.main()
        except KeyboardInterrupt:
            print("[RUNNER] stopped by user")
            break
        except Exception as e:
            # 落ちてもループ継続
            print(f"[RUNNER][ERROR] {e}")

        global _sigusr1_received
        _sigusr1_received = False

        in_pos = _has_open_position(state_path)
        sleep_sec = args.fast_interval if in_pos else args.interval
        if in_pos:
            print(f"[RUNNER] open_pos detected — fast poll {sleep_sec}s")
        try:
            time.sleep(sleep_sec)
        except KeyboardInterrupt:
            print("[RUNNER] stopped by user")
            break
        if _sigusr1_received:
            print(f"[RUNNER] SIGUSR1 received — reloading CONTROL immediately")

if __name__ == "__main__":
    main()
