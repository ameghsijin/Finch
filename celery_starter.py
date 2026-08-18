# celery_starter.py

import os
import subprocess
import sys


def start_celery():
    """Start Celery manually if needed."""
    log_path = os.path.join(os.path.dirname(__file__), "celery.log")

    try:
        if sys.platform == "win32":
            cmd = f'celery -A Finch worker --loglevel=info --logfile="{log_path}"'
            subprocess.Popen(
                cmd,
                shell=True,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:
            subprocess.Popen(
                [
                    "celery",
                    "-A",
                    "Finch",
                    "worker",
                    "--loglevel=info",
                    "--logfile",
                    log_path,
                ]
            )

        print(f"✅ Celery worker started! Logs: {log_path}")

    except Exception as e:
        print(f"❌ Celery start failed: {e}")


if __name__ == "__main__":
    start_celery()