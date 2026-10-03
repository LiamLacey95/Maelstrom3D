# SPDX-FileCopyrightText: 2026 MayaBlender
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
MEL for the MayaBlender command line: `polyCube -w 2 -n box; move -r 0 0 1;` runs the matching
`maya.cmds` command. `python("...")` runs Python with `cmds` available.
"""

__all__ = (
    "autocomplete",
    "banner",
    "execute",
    "language_id",
    "run",
)

import shlex

import bpy

language_id = "mel"
PROMPT = "MEL "


# Flags that take no value, per command (MEL knows each flag's arity; Python keyword flags don't need this).
_SWITCH_FLAGS = {
    "select": {"add", "af", "d", "deselect", "tgl", "toggle", "cl", "clear", "r", "replace", "all", "hi"},
    "move": {"r", "relative", "a", "absolute", "ws", "worldSpace", "os", "objectSpace"},
    "parent": {"w", "world", "r", "relative"},
    "delete": {"ch", "constructionHistory", "all"},
    "group": {"em", "empty", "w", "world"},
    "ls": {"sl", "selection", "dag", "tr", "transforms", "l", "long"},
    "currentTime": {"q", "query", "e", "edit"},
    "playbackOptions": {"q", "query"},
    "file": {"new", "f", "force", "o", "open", "s", "save", "rn", "rename"},
    "showHidden": {"a", "all"},
}
_SWITCH_FLAGS["rotate"] = _SWITCH_FLAGS["scale"] = _SWITCH_FLAGS["move"]
_BOOLS = {"true": True, "on": True, "yes": True, "false": False, "off": False, "no": False}


def _value(token):
    if token.lower() in _BOOLS:
        return _BOOLS[token.lower()]
    for convert in (int, float):
        try:
            return convert(token)
        except ValueError:
            pass
    return token


def _is_flag(token):
    return token.startswith("-") and isinstance(_value(token), str)


def parse(statement):
    """'move -r 0 0 1 pCube1' -> ('move', [0, 0, 1, 'pCube1'], {'r': True})."""
    tokens = shlex.split(statement, posix=True)
    command, args, flags = tokens[0], [], {}
    switches = _SWITCH_FLAGS.get(command, set())
    query = "-q" in tokens or "-query" in tokens  # In query mode every flag is a switch, like MEL.
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if _is_flag(token):
            name = token[1:]
            takes_value = not query and name not in switches
            if takes_value and i + 1 < len(tokens) and not _is_flag(tokens[i + 1]):
                flags[name] = _value(tokens[i + 1])
                i += 1
            else:
                flags[name] = True
        else:
            args.append(_value(token))
        i += 1
    return command, args, flags


def run(text):
    """Run MEL text, return the last result."""
    import maya.cmds as cmds
    result = None
    for statement in text.split(";"):
        statement = statement.split("//")[0].strip()
        if not statement:
            continue
        if statement.startswith("python("):
            code = shlex.split(statement[len("python("):].rstrip(")"))[0]
            exec(code, {"cmds": cmds, "bpy": bpy})
            continue
        command, args, flags = parse(statement)
        func = getattr(cmds, command, None)
        if func is None:
            raise NameError("Cannot find procedure \"%s\"." % command)
        result = func(*args, **flags)
    return result


def _scrollback(text, kind):
    for line in str(text).split("\n"):
        bpy.ops.console.scrollback_append(text=line, type=kind)


def execute(context, _is_interactive):
    sc = context.space_data
    try:
        line = sc.history[-1].body
    except IndexError:
        return {'CANCELLED'}
    _scrollback(sc.prompt + line, 'INPUT')
    try:
        result = run(line)
        if result is not None:
            shown = " ".join(map(str, result)) if isinstance(result, (list, tuple)) else result
            _scrollback("// Result: %s //" % shown, 'OUTPUT')
    except Exception as err:
        _scrollback("// Error: %s //" % err, 'ERROR')
    bpy.ops.console.history_append(text="", current_character=0, remove_duplicates=True)
    return {'FINISHED'}


def autocomplete(context):
    import maya.cmds as cmds
    sc = context.space_data
    line = sc.history[-1]
    word = line.body[:line.current_character].split(";")[-1].strip()
    matches = [name for name in cmds.__all__ if name.startswith(word)]
    if len(matches) == 1:
        line.body = line.body[:line.current_character - len(word)] + matches[0] + " "
        line.current_character = len(line.body)
    elif matches:
        _scrollback("  ".join(matches), 'INFO')
    return {'FINISHED'}


def banner(context):
    sc = context.space_data
    _scrollback("MEL command line: e.g. polyCube -w 2 -n box;  move -r 0 0 1;  python(\"print(cmds.ls())\")",
                'INFO')
    sc.prompt = PROMPT
    return {'FINISHED'}
