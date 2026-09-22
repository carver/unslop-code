"""End-to-end checks for the sith refactoring commands."""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import run, make, check, refactor_keeps_behaviour, \
    FAILED, PASSED  # noqa: E402

# -- errors ----------------------------------------------------------------

root = make({'ok.py': 'x = 1\n', 'bad.py': 'def f(:\n    pass\n',
             'bad2.py': 'x = (1\n'})
code, out, err = run(root, 'errors', 'ok.py')
check('errors:clean', code == 0 and json.loads(out) == {'errors': []}, out)
code, out, err = run(root, 'errors', 'bad.py')
check('errors:exit0', code == 0, err)
errs = json.loads(out)['errors']
check('errors:one', len(errs) == 1, out)
check('errors:line', errs and errs[0]['line'] == 1, out)
check('errors:fields', errs and set(errs[0]) == {
    'line', 'column', 'until_line', 'until_column', 'message'}, out)
check('errors:col0based', errs and errs[0]['column'] == 6, out)
code, out, err = run(root, 'errors', 'missing.py')
check('errors:missing', code == 1, out)
shutil.rmtree(root)

# -- rename ----------------------------------------------------------------

FILES = {
    'mod.py': 'value = 10\n\n\ndef helper(a):\n    return a + value\n',
    'main.py': ('from mod import helper, value\n\n'
                'print(helper(1) + value)\n'),
}
res = refactor_keeps_behaviour('rename:var', FILES, 'main.py',
                               ['rename', 'mod.py', '1', '0',
                                '--new-name', 'total'])
payload = res[0]
check('rename:files', sorted(payload['changed_files']) == ['main.py', 'mod.py'],
      str(sorted(payload['changed_files'])))
check('rename:renames', payload['renames'] == {}, str(payload['renames']))
check('rename:content', 'total = 10' in payload['changed_files']['mod.py'],
      payload['changed_files']['mod.py'])
shutil.rmtree(res[1])

# rename only lists files that changed
root = make(dict(FILES, other='')) if False else make(FILES)
open(os.path.join(root, 'untouched.py'), 'w').write('z = 1\n')
code, out, err = run(root, 'rename', 'mod.py', '4', '4', '--new-name', 'calc')
payload = json.loads(out)
check('rename:onlychanged',
      sorted(payload['changed_files']) == ['main.py', 'mod.py'],
      str(sorted(payload['changed_files'])))
code, out, err = run(root, 'rename', 'mod.py', '4', '4', '--new-name', 'calc',
                     '--diff')
check('rename:diff-text', out.startswith('---') and '+def calc(a):' in out, out)
check('rename:diff-nojson', not out.strip().startswith('{'), out)
# invalid names / bad cursor / collisions
for bad in ('1x', 'class', 'a b', ''):
    code, out, err = run(root, 'rename', 'mod.py', '1', '0', '--new-name', bad)
    check('rename:badname(%s)' % bad, code == 1 and out == '', out)
code, out, err = run(root, 'rename', 'mod.py', '2', '0', '--new-name', 'zz')
check('rename:nocursor', code == 1 and out == '', out)
code, out, err = run(root, 'rename', 'mod.py', '1', '0', '--new-name', 'helper')
check('rename:collision', code == 1 and out == '' and err.strip() != '', err)
shutil.rmtree(root)

# rename a local variable only touches its own scope
root = make({'a.py': 'def f():\n    x = 1\n    return x\n\n\n'
                     'def g():\n    x = 2\n    return x\n'})
code, out, err = run(root, 'rename', 'a.py', '2', '4', '--new-name', 'y')
payload = json.loads(out)
text = payload['changed_files']['a.py']
check('rename:local', text ==
      'def f():\n    y = 1\n    return y\n\n\ndef g():\n    x = 2\n'
      '    return x\n', text)
code, out, err = run(root, 'rename', 'a.py', '2', '4', '--new-name', 'g')
check('rename:harmless-shadow', code == 0, err)
shutil.rmtree(root)

root = make({'a.py': 'def f():\n    x = 1\n    return x + g()\n\n\n'
                     'def g():\n    return 2\n'})
code, out, err = run(root, 'rename', 'a.py', '2', '4', '--new-name', 'g')
check('rename:capture-collision', code == 1 and out == '', out)
shutil.rmtree(root)

# rename a method through an attribute reference
res = refactor_keeps_behaviour(
    'rename:method',
    {'m.py': 'class C:\n    def calc(self, n):\n        return n * 2\n',
     'main.py': ('from m import C\n\nobj = C()\n'
                 'print(obj.calc(1), C().calc(2))\n')},
    'main.py', ['rename', 'main.py', '4', '11', '--new-name', 'compute'])
check('rename:method-files', sorted(res[0]['changed_files']) ==
      ['m.py', 'main.py'], str(sorted(res[0]['changed_files'])))
shutil.rmtree(res[1])

# module rename
res = refactor_keeps_behaviour(
    'rename:module',
    {'mod.py': 'def hi():\n    return "hi"\n',
     'main.py': 'import mod\nfrom mod import hi\n\nprint(mod.hi(), hi())\n'},
    'main.py', ['rename', 'main.py', '1', '7', '--new-name', 'greet'])
check('rename:module-renames', res[0]['renames'] == {'mod.py': 'greet.py'},
      str(res[0]['renames']))
check('rename:module-import',
      res[0]['changed_files']['main.py'].startswith('import greet\n'
                                                    'from greet import hi'),
      res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

# package rename
res = refactor_keeps_behaviour(
    'rename:package',
    {'pkg/__init__.py': '', 'pkg/core.py': 'def go():\n    return 7\n',
     'main.py': 'from pkg.core import go\nimport pkg.core\n\n'
                'print(go(), pkg.core.go())\n'},
    'main.py', ['rename', 'main.py', '1', '5', '--new-name', 'lib'])
check('rename:package-renames', res[0]['renames'] == {'pkg': 'lib'},
      str(res[0]['renames']))
shutil.rmtree(res[1])

# module rename onto an existing name fails
root = make({'mod.py': 'x = 1\n', 'other.py': 'y = 2\n',
             'main.py': 'import mod\n'})
code, out, err = run(root, 'rename', 'main.py', '1', '7', '--new-name', 'other')
check('rename:module-collision', code == 1 and out == '', out)
shutil.rmtree(root)

# -- inline ----------------------------------------------------------------

res = refactor_keeps_behaviour(
    'inline:simple',
    {'main.py': 'def f(n):\n    base = n + 1\n    return base * 2\n\n\n'
                'print(f(3))\n'},
    'main.py', ['inline', 'main.py', '2', '4'])
text = res[0]['changed_files']['main.py']
check('inline:parens', text ==
      'def f(n):\n    return (n + 1) * 2\n\n\nprint(f(3))\n', text)
shutil.rmtree(res[1])

res = refactor_keeps_behaviour(
    'inline:noparens',
    {'main.py': 'def f():\n    x = 5\n    return x * 2\n\n\nprint(f())\n'},
    'main.py', ['inline', 'main.py', '2', '4'])
check('inline:noparens-text',
      res[0]['changed_files']['main.py'] ==
      'def f():\n    return 5 * 2\n\n\nprint(f())\n',
      res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

root = make({'a.py': 'def f():\n    x = 1\n    return 2\n'})
code, out, err = run(root, 'inline', 'a.py', '2', '4')
check('inline:unused', code == 1 and 'no references' in err, err)
code, out, err = run(root, 'inline', 'a.py', '1', '4')
check('inline:function', code == 1 and
      'cannot inline a function/class definition' in err, err)
shutil.rmtree(root)

root = make({'a.py': 'class C:\n    pass\n\n\nprint(C)\n'})
code, out, err = run(root, 'inline', 'a.py', '1', '6')
check('inline:class', code == 1 and
      'cannot inline a function/class definition' in err, err)
shutil.rmtree(root)

# -- extract-variable ------------------------------------------------------

res = refactor_keeps_behaviour(
    'extract-variable',
    {'main.py': 'def area(w, h):\n    return w * h + w * h\n\n\n'
                'print(area(2, 3))\n'},
    'main.py', ['extract-variable', 'main.py', '2', '11', '--until', '2:16',
                '--name', 'prod'])
check('extract-variable:text', res[0]['changed_files']['main.py'] ==
      'def area(w, h):\n    prod = w * h\n    return prod + w * h\n\n\n'
      'print(area(2, 3))\n', res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

root = make({'a.py': 'def area(w, h):\n    return w * h + w * h\n'})
code, out, err = run(root, 'extract-variable', 'a.py', '2', '11',
                     '--until', '2:18', '--name', 'p')
check('extract-variable:partial', code == 1 and out == '' and
      'not a complete expression' in err, err)
code, out, err = run(root, 'extract-variable', 'a.py', '2', '11',
                     '--until', '2:16', '--name', '9x')
check('extract-variable:badname', code == 1 and out == '', out)
shutil.rmtree(root)

# -- extract-function ------------------------------------------------------

res = refactor_keeps_behaviour(
    'extract-function',
    {'main.py': 'def process(items):\n    total = 0\n    count = 0\n'
                '    for item in items:\n        total += item\n'
                '        count += 1\n    return total / count\n\n\n'
                'print(process([1, 2, 3]))\n'},
    'main.py', ['extract-function', 'main.py', '4', '4', '--until', '6:18',
                '--name', 'accumulate'])
text = res[0]['changed_files']['main.py']
check('extract-function:params',
      'def accumulate(items, total, count):' in text, text)
check('extract-function:returns', 'return total, count' in text, text)
check('extract-function:call',
      '    total, count = accumulate(items, total, count)' in text, text)
check('extract-function:before',
      text.index('def accumulate') < text.index('def process'), text)
shutil.rmtree(res[1])

res = refactor_keeps_behaviour(
    'extract-function:module',
    {'main.py': 'LIMIT = 10\nvalues = [1, 2, 3]\nresult = 0\n'
                'for v in values:\n    result += v * LIMIT\n\n'
                'print(result)\n'},
    'main.py', ['extract-function', 'main.py', '4', '0', '--until', '5:23',
                '--name', 'sum_up'])
text = res[0]['changed_files']['main.py']
check('extract-function:module-params',
      'def sum_up(values, result, LIMIT):' in text, text)
check('extract-function:module-return', 'result = sum_up(' in text, text)
shutil.rmtree(res[1])

res = refactor_keeps_behaviour(
    'extract-function:single',
    {'main.py': 'def f(a):\n    b = a + 1\n    c = b * 2\n    return c\n\n\n'
                'print(f(1))\n'},
    'main.py', ['extract-function', 'main.py', '2', '4', '--until', '2:13',
                '--name', 'step'])
text = res[0]['changed_files']['main.py']
check('extract-function:single-text', 'def step(a):' in text and
      'return b' in text and '    b = step(a)' in text, text)
shutil.rmtree(res[1])

root = make({'a.py': 'def f(a):\n    b = a + 1\n    return b\n'})
code, out, err = run(root, 'extract-function', 'a.py', '2', '4',
                     '--until', '2:8', '--name', 'g')
check('extract-function:partial', code == 1 and out == '', out)
code, out, err = run(root, 'extract-function', 'a.py', '2', '4',
                     '--until', '2:13', '--name', 'def')
check('extract-function:badname', code == 1 and out == '', out)
code, out, err = run(root, 'extract-function', 'a.py', '2', '4',
                     '--until', '2:13', '--name', 'g', '--diff')
check('extract-function:diff', out.startswith('--- a/a.py') and
      '+def g(a):' in out, out)
shutil.rmtree(root)

print('\n%d checks passed, %d failed' % (PASSED[0], len(FAILED)))
sys.exit(1 if FAILED else 0)
