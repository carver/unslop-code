"""Fourth round: interpreter mode, environments, project config, context."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import run, make, check, SITH, FAILED, PASSED  # noqa: E402


def run_raw(cwd, *args):
    """Like harness.run but without the implicit --project."""
    p = subprocess.run([sys.executable, SITH] + list(args), cwd=cwd,
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def write_ns(root, name, spaces):
    path = os.path.join(root, name)
    with open(path, 'w') as fh:
        json.dump(spaces, fh)
    return name


# -- context ---------------------------------------------------------------

SRC = ('import os\n'
       '\n'
       '\n'
       'class Widget:\n'
       '    def render(self, n):\n'
       '        value = n * 2\n'
       '        return value\n'
       '\n'
       '\n'
       'def top():\n'
       '    x = 1\n'
       '    return x\n')

root = make({'a.py': SRC})
code, out, err = run(root, 'context', 'a.py', '6', '8')
check('context:exit', code == 0, err)
ctx = json.loads(out)['context']
check('context:nested', [(c['name'], c['type']) for c in ctx] ==
      [('Widget', 'class'), ('render', 'function')], out)
check('context:fields', set(ctx[0]) == {'name', 'type', 'line', 'column'}, out)
check('context:pos', ctx[0]['line'] == 4 and ctx[0]['column'] == 0, out)
check('context:pos2', ctx[1]['line'] == 5 and ctx[1]['column'] == 4, out)
code, out, err = run(root, 'context', 'a.py', '1', '0')
check('context:module', json.loads(out)['context'] == [], out)
code, out, err = run(root, 'context', 'a.py', '11', '4')
check('context:function-only',
      [c['name'] for c in json.loads(out)['context']] == ['top'], out)
shutil.rmtree(root)

# -- interpreter mode ------------------------------------------------------

NS = [
    {'df': {'type': 'DataFrame', 'module': 'pandas', 'value': '<df>',
            'attributes': ['head', 'tail']},
     'count': {'type': 'int', 'value': '42'},
     'helper': {'type': 'function', 'module': 'tools',
                'name': 'real_helper'}},
    {'count': {'type': 'str', 'value': 'later'},
     'extra': {'type': 'list'}},
]

root = make({'b.py': 'print(count)\nco\ndf.head\n', 'c.py': 'count = "s"\n'
                                                            'print(count)\n'})
write_ns(root, 'ns.json', NS)

code, out, err = run(root, 'infer', 'b.py', '1', '7', '--interpreter',
                     '--namespaces', 'ns.json')
defs = json.loads(out)['definitions']
check('interp:infer-one', len(defs) == 1, out)
check('interp:infer-type', defs and defs[0]['type'] == 'int', out)
check('interp:infer-desc',
      defs and defs[0]['description'] == 'int (runtime)', out)
check('interp:infer-name', defs and defs[0]['name'] == 'count', out)

code, out, err = run(root, 'goto', 'b.py', '1', '7', '--interpreter',
                     '--namespaces', 'ns.json')
defs = json.loads(out)['definitions']
check('interp:goto-desc',
      defs and defs[0]['description'] == 'int (runtime)', out)
check('interp:goto-type', defs and defs[0]['type'] == 'int', out)

# first namespace wins
check('interp:first-match', defs and defs[0]['docstring'] == '42', out)

# the `name` / `module` fields shape the definition
code, out, err = run(root, 'infer', 'b.py', '1', '7', '--interpreter',
                     '--namespaces', 'ns.json')
code, out, err = run(root, 'goto', 'b.py', '3', '1', '--interpreter',
                     '--namespaces', 'ns.json')
defs = json.loads(out)['definitions']
check('interp:goto-runtime-attr-owner', code == 0, err)

# completion merges static and runtime names
code, out, err = run(root, 'complete', 'b.py', '2', '2', '--interpreter',
                     '--namespaces', 'ns.json')
items = json.loads(out)['completions']
by_name = dict((c['name'], c) for c in items)
check('interp:complete-runtime', 'count' in by_name, out)
check('interp:complete-runtime-type',
      by_name.get('count', {}).get('type') == 'int', out)
check('interp:complete-runtime-desc',
      by_name.get('count', {}).get('description') == 'int (runtime)', out)
check('interp:complete-static-kept', 'compile' in by_name, out)

# static analysis wins over the namespace
code, out, err = run(root, 'infer', 'c.py', '2', '7', '--interpreter',
                     '--namespaces', 'ns.json')
defs = json.loads(out)['definitions']
check('interp:static-priority',
      defs and defs[0]['description'] == 'instance of str', out)

# runtime attributes
code, out, err = run(root, 'complete', 'b.py', '3', '3', '--interpreter',
                     '--namespaces', 'ns.json')
names = [c['name'] for c in json.loads(out)['completions']]
check('interp:attr-complete', names == ['head', 'tail'], out)

# --interpreter without --namespaces behaves like normal mode
code, out, err = run(root, 'infer', 'b.py', '1', '7', '--interpreter')
plain_code, plain_out, _ = run(root, 'infer', 'b.py', '1', '7')
check('interp:no-namespaces', (code, out) == (plain_code, plain_out), out)

# --namespaces without --interpreter is an error
code, out, err = run(root, 'infer', 'b.py', '1', '7',
                     '--namespaces', 'ns.json')
check('interp:namespaces-alone', code == 1 and err.strip() != '', out)
shutil.rmtree(root)

# -- settings --------------------------------------------------------------

root = make({'s.py': 'def Alpha():\n    pass\n\n\nal\n'})
code, out, err = run(root, 'complete', 's.py', '5', '2')
names = [c['name'] for c in json.loads(out)['completions']]
check('setting:case-default', 'Alpha' in names, out)
code, out, err = run(root, 'complete', 's.py', '5', '2',
                     '--setting', 'case_insensitive=false')
names = [c['name'] for c in json.loads(out)['completions']]
check('setting:case-off', 'Alpha' not in names, out)
code, out, err = run(root, 'complete', 's.py', '5', '2',
                     '--setting', 'add_bracket=true')
items = dict((c['name'], c['complete'])
             for c in json.loads(out)['completions'])
check('setting:add-bracket', items.get('Alpha') == 'pha(', out)
code, out, err = run(root, 'complete', 's.py', '5', '2',
                     '--setting', 'add_bracket=FALSE')
items = dict((c['name'], c['complete'])
             for c in json.loads(out)['completions'])
check('setting:add-bracket-off', items.get('Alpha') == 'pha', out)
for bad in ('nope=true', 'add_bracket=maybe', 'add_bracket'):
    code, out, err = run(root, 'complete', 's.py', '5', '2',
                         '--setting', bad)
    check('setting:bad(%s)' % bad, code == 1 and out == '', out)
shutil.rmtree(root)

# dynamic_params
root = make({'d.py': 'def f(a):\n    a\n\n\nf("x")\n'})
code, out, err = run(root, 'infer', 'd.py', '2', '4')
check('setting:dynamic-on', json.loads(out)['definitions'] != [], out)
code, out, err = run(root, 'infer', 'd.py', '2', '4',
                     '--setting', 'dynamic_params=false')
check('setting:dynamic-off', json.loads(out)['definitions'] == [], out)
shutil.rmtree(root)

# -- project init ----------------------------------------------------------

root = make({'x.py': 'x = 1\n'})
code, out, err = run(root, 'project', 'init')
check('project:init-exit', code == 0, err)
cfg_path = os.path.join(root, '.sith', 'project.json')
check('project:init-file', os.path.isfile(cfg_path), cfg_path)
cfg = json.load(open(cfg_path))
check('project:init-defaults', cfg == {
    'environment_path': '', 'sys_path': [], 'added_sys_path': [],
    'smart_sys_path': True}, str(cfg))
check('project:init-stdout', json.loads(out) == cfg, out)

code, out, err = run(root, 'project', 'init', '--environment',
                     sys.executable, '--added-sys-path', 'libs,extra')
cfg = json.load(open(cfg_path))
check('project:init-env', cfg['environment_path'] == sys.executable, str(cfg))
check('project:init-added', cfg['added_sys_path'] == ['libs', 'extra'],
      str(cfg))
code, out, err = run(root, 'project', 'init', '--sys-path', '/a,/b')
cfg = json.load(open(cfg_path))
check('project:init-merge', cfg['environment_path'] == sys.executable and
      cfg['added_sys_path'] == ['libs', 'extra'] and
      cfg['sys_path'] == ['/a', '/b'], str(cfg))
shutil.rmtree(root)

# explicit directory argument
root = tempfile.mkdtemp(prefix='sith-t-')
os.makedirs(os.path.join(root, 'sub'))
code, out, err = run_raw(root, 'project', 'init', 'sub')
check('project:init-dir', code == 0 and
      os.path.isfile(os.path.join(root, 'sub', '.sith', 'project.json')), err)
shutil.rmtree(root)

# -- project config drives import resolution -------------------------------

root = make({'mod.py': 'def go():\n    return 1\n',
             'libs/mylib.py': 'def helper():\n    return 2\n',
             'main.py': 'import mod\nimport mylib\n\n'
                        'mod.go()\nmylib.helper()\n'})
code, out, err = run(root, 'goto', 'main.py', '4', '5')
check('cfg:default-resolves', json.loads(out)['definitions'] != [], out)
code, out, err = run(root, 'goto', 'main.py', '5', '7')
check('cfg:unimportable', json.loads(out)['definitions'] == [], out)

run(root, 'project', 'init', '--added-sys-path', 'libs')
code, out, err = run(root, 'goto', 'main.py', '5', '7')
defs = json.loads(out)['definitions']
check('cfg:added-sys-path', defs and defs[0]['name'] == 'helper', out)
code, out, err = run(root, 'goto', 'main.py', '4', '5')
check('cfg:added-keeps-auto', json.loads(out)['definitions'] != [], out)

run(root, 'project', 'init', '--sys-path', 'libs')
code, out, err = run(root, 'goto', 'main.py', '4', '5')
check('cfg:sys-path-replaces', json.loads(out)['definitions'] == [], out)
code, out, err = run(root, 'goto', 'main.py', '5', '7')
check('cfg:sys-path-used', json.loads(out)['definitions'] != [], out)

run(root, 'project', 'init', '--sys-path', '', '--setting',
    'smart_sys_path=false')
code, out, err = run(root, 'goto', 'main.py', '4', '5')
check('cfg:smart-off', json.loads(out)['definitions'] == [], out)
code, out, err = run(root, 'goto', 'main.py', '4', '5', '--setting',
                     'smart_sys_path=true')
check('cfg:setting-overrides-config',
      json.loads(out)['definitions'] != [], out)
shutil.rmtree(root)

# -- env -------------------------------------------------------------------

root = make({'x.py': 'x = 1\n'})
code, out, err = run(root, 'env', 'list')
check('env:list-exit', code == 0, err)
envs = json.loads(out)['environments']
check('env:list-nonempty', len(envs) >= 1, out)
check('env:list-fields', all(set(e) == {'executable', 'version',
                                        'is_virtualenv'} for e in envs), out)
check('env:list-abs', all(os.path.isabs(e['executable']) for e in envs), out)


def vkey(entry):
    parts = [int(p) if p.isdigit() else 0
             for p in entry['version'].split('.')]
    while len(parts) < 3:
        parts.append(0)
    return (tuple(-p for p in parts[:3]), entry['executable'])


check('env:list-sorted', envs == sorted(envs, key=vkey), out)
paths = [os.path.realpath(e['executable']) for e in envs]
check('env:list-dedup-ish', len(envs) == len(set(
    (p, e['is_virtualenv']) for p, e in zip(paths, envs))), out)

code, out, err = run(root, 'env', 'info')
check('env:info-exit', code == 0, err)
info = json.loads(out)
for field in ('executable', 'version', 'is_virtualenv', 'prefix', 'sys_path'):
    check('env:info-field(%s)' % field, field in info, out)
check('env:info-syspath', isinstance(info['sys_path'], list), out)

code, out, err = run(root, 'env', 'info', sys.executable)
check('env:info-explicit', code == 0 and
      json.loads(out)['executable'] == os.path.abspath(sys.executable), out)
code, out, err = run(root, 'env', 'info',
                     os.path.join(root, 'definitely-not-python'))
check('env:info-missing', code == 1, out)

code, out, err = run(root, 'env', 'find-virtualenvs')
check('env:venvs-exit', code == 0, err)
venvs = json.loads(out)['environments']
check('env:venvs-fields', all(set(e) == {'executable', 'version',
                                         'is_virtualenv'} for e in venvs), out)
check('env:venvs-only', all(e['is_virtualenv'] for e in venvs), out)
shutil.rmtree(root)

# a fabricated virtualenv layout is found under --path
root = tempfile.mkdtemp(prefix='sith-t-')
for name, version in (('one', '3.9.7'), ('two', '3.11.6')):
    binroot = os.path.join(root, 'envs', name, 'bin')
    os.makedirs(binroot)
    with open(os.path.join(root, 'envs', name, 'pyvenv.cfg'), 'w') as fh:
        fh.write('home = /usr/bin\nversion = %s\n' % version)
    shutil.copy(sys.executable, os.path.join(binroot, 'python'))
code, out, err = run_raw(root, 'env', 'find-virtualenvs', '--path',
                         os.path.join(root, 'envs'))
found = json.loads(out)['environments']
check('env:venvs-path', len(found) == 2, out)
check('env:venvs-path-virtual', all(e['is_virtualenv'] for e in found), out)
shutil.rmtree(root)

print('\n%d checks passed, %d failed' % (PASSED[0], len(FAILED)))
sys.exit(1 if FAILED else 0)
