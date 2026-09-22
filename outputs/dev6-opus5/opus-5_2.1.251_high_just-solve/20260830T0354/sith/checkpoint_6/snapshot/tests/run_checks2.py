"""Second round of checks: trickier refactoring shapes."""
import json
import os
import shutil
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import run, make, check, refactor_keeps_behaviour, \
    FAILED, PASSED  # noqa: E402

# rename a class used across files, including in a type annotation
res = refactor_keeps_behaviour(
    'rename:class',
    {'shapes.py': ('class Box:\n    def __init__(self, w):\n'
                   '        self.w = w\n\n\n'
                   'def make(w) -> Box:\n    return Box(w)\n'),
     'main.py': ('from shapes import Box, make\n\n'
                 'b = Box(2)\nprint(b.w, make(3).w, isinstance(b, Box))\n')},
    'main.py', ['rename', 'shapes.py', '1', '6', '--new-name', 'Crate'])
text = res[0]['changed_files']['shapes.py']
check('rename:class-def', text.startswith('class Crate:'), text)
check('rename:class-annotation', '-> Crate:' in text, text)
check('rename:class-main', 'from shapes import Crate, make' in
      res[0]['changed_files']['main.py'], res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

# rename a parameter
res = refactor_keeps_behaviour(
    'rename:param',
    {'main.py': 'def f(alpha, beta):\n    return alpha * beta\n\n\n'
                'print(f(2, 3), f(4, beta=2))\n'},
    'main.py', ['rename', 'main.py', '1', '6', '--new-name', 'a'])
text = res[0]['changed_files']['main.py']
check('rename:param-def', 'def f(a, beta):' in text, text)
check('rename:param-body', 'return a * beta' in text, text)
shutil.rmtree(res[1])

# rename an import alias, leaving the module file alone
root = make({'mod.py': 'def go():\n    return 1\n',
             'main.py': 'import mod as m\n\nprint(m.go())\n'})
code, out, err = run(root, 'rename', 'main.py', '1', '14', '--new-name', 'mm')
payload = json.loads(out)
check('rename:alias-only-file', list(payload['changed_files']) == ['main.py'],
      out)
check('rename:alias-norename', payload['renames'] == {}, out)
check('rename:alias-text',
      payload['changed_files']['main.py'] ==
      'import mod as mm\n\nprint(mm.go())\n', out)
shutil.rmtree(root)

# renaming the module through an aliased import still renames the file
root = make({'mod.py': 'def go():\n    return 1\n',
             'main.py': 'import mod as m\n\nprint(m.go())\n'})
code, out, err = run(root, 'rename', 'main.py', '1', '7', '--new-name', 'core')
payload = json.loads(out)
check('rename:aliased-module', payload['renames'] == {'mod.py': 'core.py'},
      out)
check('rename:aliased-module-text',
      payload['changed_files']['main.py'] ==
      'import core as m\n\nprint(m.go())\n', out)
shutil.rmtree(root)

# rename inside a comprehension
res = refactor_keeps_behaviour(
    'rename:comprehension',
    {'main.py': 'nums = [1, 2, 3]\nsquares = [n * n for n in nums]\n'
                'print(squares)\n'},
    'main.py', ['rename', 'main.py', '2', '11', '--new-name', 'value'])
check('rename:comprehension-text',
      '[value * value for value in nums]' in
      res[0]['changed_files']['main.py'],
      res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

# inline a tuple: parentheses are required
res = refactor_keeps_behaviour(
    'inline:tuple',
    {'main.py': 'pair = 1, 2\nprint(len(pair))\n'},
    'main.py', ['inline', 'main.py', '1', '0'])
check('inline:tuple-text',
      res[0]['changed_files']['main.py'] == 'print(len((1, 2)))\n',
      res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

# inline a call value used twice
res = refactor_keeps_behaviour(
    'inline:call',
    {'main.py': 'def f():\n    return 3\n\n\ndef g():\n    v = f()\n'
                '    return v + v\n\n\nprint(g())\n'},
    'main.py', ['inline', 'main.py', '6', '4'])
check('inline:call-text', 'return f() + f()' in
      res[0]['changed_files']['main.py'], res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

# inline a unary/power expression into an exponent
res = refactor_keeps_behaviour(
    'inline:power',
    {'main.py': 'e = 1 + 1\nprint(2 ** e, -e)\n'},
    'main.py', ['inline', 'main.py', '1', '0'])
check('inline:power-text',
      res[0]['changed_files']['main.py'] == 'print(2 ** (1 + 1), -(1 + 1))\n',
      res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

# inline into an f-string / subscript / comparison chain
res = refactor_keeps_behaviour(
    'inline:mixed',
    {'main.py': 'idx = 1 + 1\ndata = [0, 1, 2, 3]\n'
                'print(data[idx], idx < 3, [idx])\n'},
    'main.py', ['inline', 'main.py', '1', '0'])
text = res[0]['changed_files']['main.py']
check('inline:mixed-text', 'data[1 + 1]' in text and '1 + 1 < 3' in text,
      text)
shutil.rmtree(res[1])

# inline where the definition is not a simple assignment
root = make({'a.py': 'for i in range(3):\n    print(i)\n'})
code, out, err = run(root, 'inline', 'a.py', '1', '4')
check('inline:loop-target', code == 1 and out == '', out)
shutil.rmtree(root)

root = make({'a.py': 'x = 1\nx = 2\nprint(x)\n'})
code, out, err = run(root, 'inline', 'a.py', '1', '0')
check('inline:reassigned', code == 1 and out == '', out)
shutil.rmtree(root)

# extract-variable of a call and of a nested expression
res = refactor_keeps_behaviour(
    'extract-variable:call',
    {'main.py': 'def f(xs):\n    return sorted(xs)[0] + sorted(xs)[-1]\n\n\n'
                'print(f([3, 1, 2]))\n'},
    'main.py', ['extract-variable', 'main.py', '2', '11', '--until', '2:21',
                '--name', 'ordered'])
text = res[0]['changed_files']['main.py']
check('extract-variable:call-text',
      '    ordered = sorted(xs)\n    return ordered[0] + sorted(xs)[-1]\n'
      in text, text)
shutil.rmtree(res[1])

res = refactor_keeps_behaviour(
    'extract-variable:module',
    {'main.py': 'print((2 + 3) * 4)\n'},
    'main.py', ['extract-variable', 'main.py', '1', '6', '--until', '1:13',
                '--name', 'base'])
check('extract-variable:module-text',
      res[0]['changed_files']['main.py'] ==
      'base = 2 + 3\nprint((base) * 4)\n',
      res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

# extract-function with neither parameters nor return values
res = refactor_keeps_behaviour(
    'extract-function:bare',
    {'main.py': 'def main():\n    print("a")\n    print("b")\n'
                '    return 0\n\n\nmain()\n'},
    'main.py', ['extract-function', 'main.py', '2', '4', '--until', '3:15',
                '--name', 'show'])
text = res[0]['changed_files']['main.py']
check('extract-function:bare-def', 'def show():' in text, text)
check('extract-function:bare-call', '    show()\n' in text, text)
check('extract-function:bare-noreturn', 'return' not in
      text.split('def main')[0], text)
shutil.rmtree(res[1])

# extract-function keeps nested blocks and picks up decorators
res = refactor_keeps_behaviour(
    'extract-function:decorated',
    {'main.py': 'def deco(fn):\n    return fn\n\n\n@deco\ndef work(n):\n'
                '    out = []\n    for i in range(n):\n'
                '        if i % 2:\n            out.append(i)\n'
                '    return out\n\n\nprint(work(6))\n'},
    'main.py', ['extract-function', 'main.py', '8', '4', '--until', '10:26',
                '--name', 'collect'])
text = res[0]['changed_files']['main.py']
check('extract-function:decorated-before',
      text.index('def collect(') < text.index('@deco'), text)
check('extract-function:decorated-params',
      'def collect(n, out):' in text, text)
check('extract-function:decorated-return', 'return out' in text, text)
shutil.rmtree(res[1])

# extract-function inside an if block at module level
res = refactor_keeps_behaviour(
    'extract-function:nested-module',
    {'main.py': 'flag = True\nif flag:\n    a = 1\n    b = a + 1\n'
                '    print(b)\n'},
    'main.py', ['extract-function', 'main.py', '3', '4', '--until', '4:13',
                '--name', 'setup'])
text = res[0]['changed_files']['main.py']
check('extract-function:nested-module-indent',
      '    def setup():' in text, text)
check('extract-function:nested-module-call', '    b = setup()' in text, text)
shutil.rmtree(res[1])

# a selection that cuts a compound statement in half is rejected
root = make({'a.py': 'def f(n):\n    for i in range(n):\n        print(i)\n'
                     '    return n\n'})
code, out, err = run(root, 'extract-function', 'a.py', '2', '4',
                     '--until', '2:22', '--name', 'g')
check('extract-function:half-loop', code == 1 and out == '', out)
code, out, err = run(root, 'extract-function', 'a.py', '3', '8',
                     '--until', '4:12', '--name', 'g')
check('extract-function:cross-block', code == 1 and out == '', out)
shutil.rmtree(root)

# errors: unterminated string, bad indentation, empty file, only comments
root = make({'s.py': 'x = "abc\n', 'i.py': 'def f():\nreturn 1\n',
             'e.py': '', 'c.py': '# nothing here\n',
             'tab.py': 'def f():\n    x = 1\n     y = 2\n'})
for name, expect in (('s.py', 1), ('i.py', 1), ('e.py', 0), ('c.py', 0),
                     ('tab.py', 1)):
    code, out, err = run(root, 'errors', name)
    got = json.loads(out)['errors']
    check('errors:%s' % name, code == 0 and len(got) == expect, out)
    for entry in got:
        check('errors:%s-shape' % name,
              entry['line'] >= 1 and entry['column'] >= 0 and
              entry['until_line'] >= entry['line'] and
              isinstance(entry['message'], str) and entry['message'] != '',
              str(entry))
shutil.rmtree(root)

# diffs are plain text for every refactoring command
root = make({'a.py': 'def f(n):\n    v = n + 1\n    return v * 2\n'})
for args in (['rename', 'a.py', '2', '4', '--new-name', 'w'],
             ['inline', 'a.py', '2', '4'],
             ['extract-variable', 'a.py', '2', '8', '--until', '2:13',
              '--name', 'q'],
             ['extract-function', 'a.py', '2', '4', '--until', '2:13',
              '--name', 'g']):
    code, out, err = run(root, *(args + ['--diff']))
    check('diff:%s' % args[0], code == 0 and out.startswith('--- a/a.py\n') and
          '+++ b/a.py\n' in out and '@@' in out, out)
    check('diff:%s-nojson' % args[0], '"changed_files"' not in out, out)
shutil.rmtree(root)


# an expression inside a decorator lifts out above the decorator
res = refactor_keeps_behaviour(
    'extract-variable:decorator',
    {'main.py': ('def deco(n):\n    def wrap(fn):\n        return fn\n'
                 '    return wrap\n\n\n@deco(2 + 3)\n'
                 'def target(a=4 * 5):\n    return a\n\n\n'
                 'print(target())\n')},
    'main.py', ['extract-variable', 'main.py', '7', '6', '--until', '7:11',
                '--name', 'k'])
text = res[0]['changed_files']['main.py']
check('extract-variable:decorator-text', 'k = 2 + 3\n@deco(k)\n' in text, text)
shutil.rmtree(res[1])

# a decorated definition can only be selected together with its decorator
root = make({'a.py': ('def deco(fn):\n    return fn\n\n\n@deco\n'
                      'def f():\n    return 1\n')})
code, out, err = run(root, 'extract-function', 'a.py', '6', '0',
                     '--until', '7:12', '--name', 'g')
check('extract-function:decorator-partial', code == 1 and out == '', out)
code, out, err = run(root, 'extract-function', 'a.py', '5', '0',
                     '--until', '7:12', '--name', 'g')
check('extract-function:decorator-whole', code == 0, err)
if code == 0:
    text = json.loads(out)['changed_files']['a.py']
    check('extract-function:decorator-body', '    @deco\n    def f():' in text,
          text)
shutil.rmtree(root)

print('\n%d checks passed, %d failed' % (PASSED[0], len(FAILED)))
sys.exit(1 if FAILED else 0)
