"""Shared helpers for the sith command checks."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

SITH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'sith.py')
FAILED = []
PASSED = [0]


def run(root, *args):
    cmd = [sys.executable, SITH] + list(args) + ['--project', root]
    p = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def make(files):
    root = tempfile.mkdtemp(prefix='sith-t-')
    for name, text in files.items():
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as fh:
            fh.write(text)
    return root


def check(label, cond, detail=''):
    if cond:
        PASSED[0] += 1
    else:
        FAILED.append('%s %s' % (label, detail))
        print('FAIL: %s %s' % (label, detail))


def apply_changes(root, payload):
    for rel, text in payload['changed_files'].items():
        with open(os.path.join(root, rel), 'w') as fh:
            fh.write(text)
    for old, new in payload['renames'].items():
        os.rename(os.path.join(root, old), os.path.join(root, new))


def output_of(root, script):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    p = subprocess.run([sys.executable, script], cwd=root,
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stdout + p.stderr


def refactor_keeps_behaviour(label, files, entry, args):
    """Run *entry* before and after the refactor and compare output."""
    root = make(files)
    before = output_of(root, entry)
    code, out, err = run(root, *args)
    check(label + ':exit', code == 0, err)
    if code != 0:
        shutil.rmtree(root)
        return None
    payload = json.loads(out)
    apply_changes(root, payload)
    after = output_of(root, entry)
    check(label + ':behaviour', before == after,
          '%r != %r' % (before, after))
    result = (payload, root)
    return result


