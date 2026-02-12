# run.py
import time
import argparse
from datetime import datetime
import bot

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=int, default=300, help="実行間隔（秒）例: 300=5分, 600=10分")
    p.add_argument("--print-tick", action="store_true", help="毎回tick時刻を表示する")
    return p.parse_args()

def main():
    args = parse_args()
    print(f"[RUNNER] interval={args.interval}s で bot.main() を実行します。Ctrl+Cで停止。")

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

        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print("[RUNNER] stopped by user")
            break

if __name__ == "__main__":
    main()
