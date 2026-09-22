"""The `signatures` command: what the call around the cursor is calling."""

import ast
import inspect

from .calls import POSITIONAL, Kind, Parameter, call_at, parameter_index
from .classes import is_method
from .evaluator import Evaluator
from .modules import project_at
from .navigation import context_at
from .values import ClassValue, FunctionValue, LiveValue, typed_variants


def signatures(path, line, column, dynamic, options):
    """The signatures of the callable whose argument list holds the cursor."""
    project = project_at(options)
    module = project.module(path)
    call = call_at(module.lines, line, column)
    if call is None:
        return []
    evaluator = Evaluator(project, dynamic and options.settings.dynamic_params,
                          options.namespace)
    called = evaluator.infer(call.callee, context_at(module, line))
    found = dict(
        record
        for value in called
        for record in _records(evaluator, value, call.arguments)
    )
    return [found[key] for key in sorted(found)]


def _records(evaluator, value, arguments):
    """The (sort key, record) pairs one inferred callable contributes."""
    if isinstance(value, ClassValue) and not value.instance:
        return _class_records(evaluator, value, arguments)
    if isinstance(value, FunctionValue):
        written = ast.get_docstring(value.node) or ""
        return _function_records(value, value.node.name, written, arguments)
    if isinstance(value, LiveValue) and callable(value.obj):
        return _live_records(value, arguments)
    return []


def _class_records(evaluator, value, arguments):
    """A class is called through its ``__init__``, under the class's own name."""
    name = value.node.name
    docstring = ast.get_docstring(value.node) or ""
    found = [
        record
        for initialiser in evaluator.member_values([value], "__init__")
        if isinstance(initialiser, FunctionValue)
        for record in _function_records(initialiser, name, docstring, arguments)
    ]
    return found or [(_key(value, name), _shown(name, [], arguments, None, docstring))]


def _function_records(function, name, docstring, arguments):
    """One record per declaration of a function: each stub overload, or its own.

    `docstring` is what a declaration that carries none falls back to, which
    is how a stub borrows the docstring of the source it types.
    """
    return [
        (_key(variant, name),
         _record(variant.node, name, _parameters(variant), docstring, arguments))
        for variant in typed_variants(function)
    ]


def _record(node, name, parameters, docstring, arguments):
    """The signature record printed for one declaration of a function."""
    returns = None if node.returns is None else ast.unparse(node.returns)
    return _shown(name, parameters, arguments, returns, ast.get_docstring(node) or docstring)


def _shown(name, parameters, arguments, returns, docstring):
    """How one signature is printed, whatever source it was read from."""
    rendered = [parameter.text for parameter in parameters]
    declared = f"def {name}({', '.join(rendered)})"
    return {
        "name": name,
        "params": rendered,
        "index": parameter_index(parameters, arguments),
        "description": declared if returns is None else f"{declared} -> {returns}",
        "docstring": docstring,
    }


def _key(value, name):
    """Where a callable is declared, as the (module path, line) records sort by."""
    definition = value.definition()
    return definition.module_path, definition.line, name


def _parameters(function):
    """The parameters a caller supplies, in the order a call binds them."""
    declared = _declared(function.node.args)
    hides_receiver = (declared and declared[0].kind in POSITIONAL
                      and is_method(function.module, function.node))
    return declared[1:] if hides_receiver else declared


def _declared(arguments):
    """Every parameter of a signature, rendered as the source writes it."""
    positional = arguments.posonlyargs + arguments.args
    kinds = ([Kind.POSITIONAL_ONLY] * len(arguments.posonlyargs)
             + [Kind.POSITIONAL_OR_KEYWORD] * len(arguments.args))
    defaults = [None] * (len(positional) - len(arguments.defaults)) + list(arguments.defaults)
    declared = [_parameter(argument, default, kind)
                for argument, default, kind in zip(positional, defaults, kinds)]
    if arguments.vararg is not None:
        declared.append(_parameter(arguments.vararg, None, Kind.VAR_POSITIONAL, "*"))
    declared += [_parameter(argument, default, Kind.KEYWORD_ONLY)
                 for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults)]
    if arguments.kwarg is not None:
        declared.append(_parameter(arguments.kwarg, None, Kind.VAR_KEYWORD, "**"))
    return declared


def _parameter(argument, default, kind, prefix=""):
    text = f"{prefix}{argument.arg}"
    if argument.annotation is not None:
        text += f": {ast.unparse(argument.annotation)}"
    if default is not None:
        text += f"={ast.unparse(default)}"
    return Parameter(argument.arg, text, kind)


def _live_records(value, arguments):
    """The signature an imported object reports; C callables report none."""
    try:
        declared = inspect.signature(value.obj)
    except (TypeError, ValueError):
        return []
    definition = value.definition()
    record = _shown(
        definition.name,
        [_live_parameter(parameter) for parameter in declared.parameters.values()],
        arguments,
        _live_returns(declared),
        definition.docstring,
    )
    return [((definition.module_path, definition.line, definition.name), record)]


def _live_parameter(parameter):
    """One parameter of a live signature, written the way source would write it."""
    prefix = {Kind.VAR_POSITIONAL: "*", Kind.VAR_KEYWORD: "**"}.get(parameter.kind, "")
    text = f"{prefix}{parameter.name}"
    if parameter.annotation is not parameter.empty:
        text += f": {inspect.formatannotation(parameter.annotation)}"
    if parameter.default is not parameter.empty:
        text += f"={parameter.default!r}"
    return Parameter(parameter.name, text, parameter.kind)


def _live_returns(declared):
    """The return type a live signature reports, written the way source would."""
    if declared.return_annotation is declared.empty:
        return None
    return inspect.formatannotation(declared.return_annotation)
