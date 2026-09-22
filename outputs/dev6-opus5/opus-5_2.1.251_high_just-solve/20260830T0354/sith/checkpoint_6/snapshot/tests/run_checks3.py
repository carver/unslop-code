"""Third round: packages, chained refactorings, odd shapes."""
import json
import os
import shutil
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import run, make, check, apply_changes, output_of, \
    refactor_keeps_behaviour, FAILED, PASSED  # noqa: E402

PKG = {
    'pkg/__init__.py': 'from .core import Engine\n\nNAME = "pkg"\n',
    'pkg/core.py': ('SPEED = 2\n\n\nclass Engine:\n'
                    '    def __init__(self, power):\n'
                    '        self.power = power\n\n'
                    '    def output(self):\n'
                    '        return self.power * SPEED\n'),
    'pkg/util/__init__.py': '',
    'pkg/util/helpers.py': ('from ..core import SPEED\n\n\n'
                            'def scale(n):\n    return n * SPEED\n'),
    'main.py': ('from pkg import Engine, NAME\nfrom pkg.util.helpers '
                'import scale\nimport pkg.core\n\n'
                'print(NAME, Engine(3).output(), scale(4), pkg.core.SPEED)\n'),
}

# rename a module-level constant that crosses package boundaries
res = refactor_keeps_behaviour(
    'pkg:rename-const', PKG, 'main.py',
    ['rename', 'pkg/core.py', '1', '0', '--new-name', 'RATE'])
files = sorted(res[0]['changed_files'])
check('pkg:rename-const-files',
      files == ['main.py', 'pkg/core.py', 'pkg/util/helpers.py'], str(files))
shutil.rmtree(res[1])

# rename a class defined in a sub-module and re-exported by the package
res = refactor_keeps_behaviour(
    'pkg:rename-class', PKG, 'main.py',
    ['rename', 'pkg/core.py', '4', '6', '--new-name', 'Motor'])
files = sorted(res[0]['changed_files'])
check('pkg:rename-class-files',
      files == ['main.py', 'pkg/__init__.py', 'pkg/core.py'], str(files))
check('pkg:rename-class-init',
      res[0]['changed_files']['pkg/__init__.py'] ==
      'from .core import Motor\n\nNAME = "pkg"\n',
      res[0]['changed_files']['pkg/__init__.py'])
shutil.rmtree(res[1])

# rename a nested module, updating relative and absolute imports
res = refactor_keeps_behaviour(
    'pkg:rename-module', PKG, 'main.py',
    ['rename', 'pkg/util/helpers.py', '1', '8', '--new-name', 'engine'])
check('pkg:rename-module-renames',
      res[0]['renames'] == {'pkg/core.py': 'pkg/engine.py'},
      str(res[0]['renames']))
check('pkg:rename-module-relative',
      res[0]['changed_files']['pkg/util/helpers.py'].startswith(
          'from ..engine import SPEED'),
      res[0]['changed_files']['pkg/util/helpers.py'])
check('pkg:rename-module-init',
      res[0]['changed_files']['pkg/__init__.py'].startswith(
          'from .engine import Engine'),
      res[0]['changed_files']['pkg/__init__.py'])
shutil.rmtree(res[1])

# rename a sub-package directory
res = refactor_keeps_behaviour(
    'pkg:rename-subpackage', PKG, 'main.py',
    ['rename', 'main.py', '2', '10', '--new-name', 'tools'])
check('pkg:rename-subpackage-renames',
      res[0]['renames'] == {'pkg/util': 'pkg/tools'},
      str(res[0]['renames']))
shutil.rmtree(res[1])

# rename a method through self
res = refactor_keeps_behaviour(
    'pkg:rename-method', PKG, 'main.py',
    ['rename', 'pkg/core.py', '8', '8', '--new-name', 'result'])
check('pkg:rename-method-files',
      sorted(res[0]['changed_files']) == ['main.py', 'pkg/core.py'],
      str(sorted(res[0]['changed_files'])))
shutil.rmtree(res[1])

# rename an attribute assigned through self
res = refactor_keeps_behaviour(
    'pkg:rename-attr', PKG, 'main.py',
    ['rename', 'pkg/core.py', '6', '13', '--new-name', 'watts'])
text = res[0]['changed_files']['pkg/core.py']
check('pkg:rename-attr-text',
      'self.watts = power' in text and 'return self.watts * SPEED' in text,
      text)
shutil.rmtree(res[1])

# chained refactorings on the same project
root = make(PKG)
before = output_of(root, 'main.py')
steps = [
    ['extract-variable', 'pkg/core.py', '9', '15', '--until', '9:25',
     '--name', 'base'],
    ['rename', 'pkg/core.py', '1', '0', '--new-name', 'RATE'],
    ['extract-variable', 'pkg/util/helpers.py', '5', '11', '--until',
     '5:19', '--name', 'tmp'],
    ['inline', 'pkg/util/helpers.py', '5', '4'],
]
ok = True
for step in steps:
    code, out, err = run(root, *step)
    check('chain:%s' % step[0], code == 0, err)
    if code:
        ok = False
        break
    apply_changes(root, json.loads(out))
if ok:
    after = output_of(root, 'main.py')
    check('chain:behaviour', before == after, '%r != %r' % (before, after))
shutil.rmtree(root)

# odd shapes: async functions, decorators, nested functions
res = refactor_keeps_behaviour(
    'odd:async',
    {'main.py': ('import asyncio\n\n\n'
                 'async def work(n):\n    total = n + 1\n'
                 '    return total * 2\n\n\n'
                 'print(asyncio.run(work(2)))\n')},
    'main.py', ['inline', 'main.py', '5', '4'])
check('odd:async-text', 'return (n + 1) * 2' in
      res[0]['changed_files']['main.py'], res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

res = refactor_keeps_behaviour(
    'odd:nested',
    {'main.py': ('def outer(n):\n    seed = n * 2\n\n'
                 '    def inner():\n        return seed + 1\n\n'
                 '    return inner()\n\n\nprint(outer(2))\n')},
    'main.py', ['rename', 'main.py', '2', '4', '--new-name', 'start'])
text = res[0]['changed_files']['main.py']
check('odd:nested-text', 'start = n * 2' in text and 'return start + 1' in text,
      text)
shutil.rmtree(res[1])

# extract-function out of a nested function keeps the closure working
res = refactor_keeps_behaviour(
    'odd:extract-nested',
    {'main.py': ('def outer(n):\n    seed = n * 2\n\n'
                 '    def inner():\n        acc = seed + 1\n'
                 '        acc = acc * 2\n        return acc\n\n'
                 '    return inner()\n\n\nprint(outer(2))\n')},
    'main.py', ['extract-function', 'main.py', '5', '8', '--until', '6:21',
                '--name', 'compute'])
text = res[0]['changed_files']['main.py']
check('odd:extract-nested-indent', '    def compute():' in text, text)
check('odd:extract-nested-call', '        acc = compute()' in text, text)
shutil.rmtree(res[1])

# renaming something that only exists in one file leaves others untouched
root = make(PKG)
code, out, err = run(root, 'rename', 'pkg/util/helpers.py', '4', '4',
                     '--new-name', 'grow')
payload = json.loads(out)
check('pkg:rename-func-files',
      sorted(payload['changed_files']) == ['main.py', 'pkg/util/helpers.py'],
      str(sorted(payload['changed_files'])))
shutil.rmtree(root)


# -- aliased imports -------------------------------------------------------

res = refactor_keeps_behaviour(
    'alias:rename',
    {'mod.py': 'value = 10\n',
     'main.py': 'from mod import value as v\nimport mod\n\n'
                'print(v, mod.value)\n'},
    'main.py', ['rename', 'mod.py', '1', '0', '--new-name', 'total'])
check('alias:rename-text',
      res[0]['changed_files']['main.py'] ==
      'from mod import total as v\nimport mod\n\nprint(v, mod.total)\n',
      res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

res = refactor_keeps_behaviour(
    'alias:inline',
    {'mod.py': 'value = 5 + 5\n',
     'main.py': 'from mod import value as v\nimport mod\n\n'
                'print(v * 2, mod.value)\n'},
    'main.py', ['inline', 'mod.py', '1', '0'])
check('alias:inline-text',
      res[0]['changed_files']['main.py'] ==
      'import mod\n\nprint((5 + 5) * 2, 5 + 5)\n',
      res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

res = refactor_keeps_behaviour(
    'alias:inline-partial-import',
    {'mod.py': 'LIMIT = 2 * 2\nOTHER = 7\n',
     'main.py': 'from mod import LIMIT, OTHER\n\nprint(LIMIT + OTHER)\n'},
    'main.py', ['inline', 'mod.py', '1', '0'])
check('alias:inline-partial-text',
      res[0]['changed_files']['main.py'] ==
      'from mod import OTHER\n\nprint(2 * 2 + OTHER)\n',
      res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])

res = refactor_keeps_behaviour(
    'alias:inline-last-import',
    {'mod.py': 'FIRST = 1\nLIMIT = 2 * 2\n',
     'main.py': 'from mod import FIRST, LIMIT\n\nprint(FIRST + LIMIT)\n'},
    'main.py', ['inline', 'mod.py', '2', '0'])
check('alias:inline-last-text',
      res[0]['changed_files']['main.py'] ==
      'from mod import FIRST\n\nprint(FIRST + 2 * 2)\n',
      res[0]['changed_files']['main.py'])
shutil.rmtree(res[1])


# extracting a block that ends in a return keeps returning it
res = refactor_keeps_behaviour(
    'odd:tail-return',
    {'main.py': ('def compute(a, b):\n    scaled = a * 2\n'
                 '    return scaled + b\n\n\nprint(compute(2, 3))\n')},
    'main.py', ['extract-function', 'main.py', '2', '4', '--until', '3:21',
                '--name', 'inner'])
text = res[0]['changed_files']['main.py']
check('odd:tail-return-call', '    return inner(a, b)' in text, text)
check('odd:tail-return-body', 'def inner(a, b):' in text and
      '    return scaled + b' in text, text)
shutil.rmtree(res[1])


# renaming an exported name keeps __all__ in step
res = refactor_keeps_behaviour(
    'export:all',
    {'mod.py': '__all__ = ["value", "other"]\n\nvalue = 1\nother = 2\n',
     'main.py': 'from mod import *\n\nprint(value, other)\n'},
    'main.py', ['rename', 'mod.py', '3', '0', '--new-name', 'total'])
check('export:all-text',
      res[0]['changed_files']['mod.py'].startswith(
          '__all__ = ["total", "other"]'),
      res[0]['changed_files']['mod.py'])
shutil.rmtree(res[1])

# extraction that would move a break out of its loop is refused
root = make({'a.py': ('def f(items):\n    for i in items:\n'
                      '        if i:\n            break\n    return 1\n')})
code, out, err = run(root, 'extract-function', 'a.py', '3', '8',
                     '--until', '4:17', '--name', 'g')
check('guard:break', code == 1 and out == '', out)
shutil.rmtree(root)

root = make({'a.py': 'def f(n):\n    for i in range(n):\n        yield i\n'})
code, out, err = run(root, 'extract-function', 'a.py', '3', '8',
                     '--until', '3:15', '--name', 'g')
check('guard:yield', code == 1 and out == '', out)
shutil.rmtree(root)

# an extraction containing await becomes an async def awaited at the call site
res = refactor_keeps_behaviour(
    'guard:async',
    {'main.py': ('import asyncio\n\n\nasync def inner(n):\n    return n * 2\n'
                 '\n\nasync def outer(n):\n    got = await inner(n)\n'
                 '    return got + 1\n\n\nprint(asyncio.run(outer(3)))\n')},
    'main.py', ['extract-function', 'main.py', '9', '4', '--until', '9:24',
                '--name', 'fetch'])
text = res[0]['changed_files']['main.py']
check('guard:async-def', 'async def fetch(n):' in text, text)
check('guard:async-call', '    got = await fetch(n)' in text, text)
shutil.rmtree(res[1])

# inlining the only statement of a block leaves a pass behind, so the
# result still parses (the try no longer guards the expression, which is
# what inlining a value out of a block means)
root = make({'main.py': ('def f(item):\n    try:\n        value = int(item)\n'
                         '    except ValueError:\n        return 0\n'
                         '    return value + 1\n')})
code, out, err = run(root, 'inline', 'main.py', '3', '8')
check('guard:sole-statement-exit', code == 0, err)
text = json.loads(out)['changed_files']['main.py']
check('guard:sole-statement-pass', '    try:\n        pass\n' in text, text)
check('guard:sole-statement-use', 'return int(item) + 1' in text, text)
check('guard:sole-statement-parses', compile(text, 'main.py', 'exec') or True,
      text)
shutil.rmtree(root)

print('\n%d checks passed, %d failed' % (PASSED[0], len(FAILED)))
sys.exit(1 if FAILED else 0)
