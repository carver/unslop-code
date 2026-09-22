"""Run every check suite; exit non-zero when any check fails."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ['run_checks.py', 'run_checks2.py', 'run_checks3.py']

failed = 0
for name in SUITES:
    print('== %s' % name)
    result = subprocess.run([sys.executable, os.path.join(HERE, name)])
    failed += result.returncode != 0
sys.exit(1 if failed else 0)
