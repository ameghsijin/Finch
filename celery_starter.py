# celery_starter.py

import os
import subprocess
import sys
import threading
import time

def start_celery():
    """Start Celery in background thread"""
    def run():
        try:
            log_path = os.path.join(os.path.dirname(__file__), 'celery.log')

            if sys.platform == 'win32':
                cmd = f'celery -A Finch worker --loglevel=info --logfile="{log_path}"'
                subprocess.Popen(cmd, shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                # Kill existing celery first
                subprocess.run(['pkill', '-f', 'celery'], capture_output=True)
                time.sleep(0.5)
                # Start new celery, logging to file instead of discarding output
                subprocess.Popen(
                    [
                        'celery', '-A', 'Finch', 'worker',
                        '--loglevel=info',
                        '--logfile', log_path,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            print(f"✅ Celery worker started! Logs: {log_path}")
        except Exception as e:
            print(f"❌ Celery start failed: {e}")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread

# Auto-start when imported
if __name__ != "__main__":
    start_celery()