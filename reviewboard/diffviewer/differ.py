"""Base definitions for differ implementations."""

from __future__ import annotations

import os
from typing import Any, Literal, Optional, TYPE_CHECKING

from reviewboard.diffviewer.errors import DiffCompatError
from reviewboard.diffviewer.filetypes import (HEADER_REGEXES,
                                              HEADER_REGEX_ALIASES)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from typing_extensions import TypeAlias


# Compatibility versions:
#
class DiffCompatVersion(object):
    # Python SequenceMatcher differ.
    SMDIFFER = 0

    # Myers differ
    MYERS = 1

    # Myers differ with bailing on a too high SMS cost
    # (prevents very long diff times for certain files)
    MYERS_SMS_COST_BAIL = 2

    DEFAULT = MYERS_SMS_COST_BAIL

    MYERS_VERSIONS = (MYERS, MYERS_SMS_COST_BAIL)


#: The potential values for opcode tags.
#:
#: Version Added:
#:     8.0
DiffOpcodeTag: TypeAlias = Literal[
    'delete',
    'equal',
    'filtered-equal',
    'insert',
    'replace',
]


#: The structure used for opcodes.
#:
#: Version Added:
#:     8.0
DiffOpcode: TypeAlias = tuple[
    DiffOpcodeTag,  # tag
    int,  # i1
    int,  # i2
    int,  # j1
    int,  # j2
]


#: The structure used for opcodes with metadata.
#:
#: Version Added:
#:     8.0
DiffOpcodeWithMetadata: TypeAlias = tuple[
    DiffOpcodeTag,  # tag
    int,  # i1
    int,  # i2
    int,  # j1
    int,  # j2
    Optional[dict[str, Any]],  # metadata
]


class Differ(object):
    """Base class for differs."""
    def __init__(self, a, b, ignore_space=False, compat_version=None):
        if type(a) is not type(b):
            raise TypeError

        self.a = a
        self.b = b
        self.ignore_space = ignore_space
        self.compat_version = compat_version
        self.interesting_line_regexes = []
        self.interesting_lines = [{}, {}]

    def add_interesting_line_regex(self, name, regex):
        """Registers a regular expression used to look for interesting lines.

        All interesting lines found that match the regular expression will
        be stored and tagged with the given name. Callers can use
        get_interesting_lines to get the results.
        """
        self.interesting_line_regexes.append((name, regex))
        self.interesting_lines[0][name] = []
        self.interesting_lines[1][name] = []

    def add_interesting_lines_for_headers(self, filename):
        """Registers for interesting lines for headers based on filename.

        This is a convenience over add_interesting_line_regex that will watch
        for headers (functions, classes, etc.) for the file type matching
        the given filename.
        """
        regexes = []

        if filename in HEADER_REGEX_ALIASES:
            regexes = HEADER_REGEXES[HEADER_REGEX_ALIASES[filename]]
        else:
            basename, ext = os.path.splitext(filename)

            if ext in HEADER_REGEXES:
                regexes = HEADER_REGEXES[ext]
            elif ext in HEADER_REGEX_ALIASES:
                regexes = HEADER_REGEXES[HEADER_REGEX_ALIASES[ext]]

        for regex in regexes:
            self.add_interesting_line_regex('header', regex)

    def get_interesting_lines(self, name, is_modified_file):
        """Returns the interesting lines tagged with the given name."""
        if is_modified_file:
            index = 1
        else:
            index = 0

        return self.interesting_lines[index].get(name, [])

    def get_opcodes(self) -> Iterator[DiffOpcode]:
        """Yield the opcodes for the diff.

        Yields:
            DiffOpcode:
            The opcodes for the diff.
        """
        raise NotImplementedError


def get_differ(a, b, ignore_space=False,
               compat_version=DiffCompatVersion.DEFAULT):
    """Returns a differ for with the given settings.

    By default, this will return the MyersDiffer. Older differs can be used
    by specifying a compat_version, but this is only for *really* ancient
    diffs, currently.
    """
    cls = None

    if compat_version in DiffCompatVersion.MYERS_VERSIONS:
        from reviewboard.diffviewer.myersdiff import MyersDiffer
        cls = MyersDiffer
    elif compat_version == DiffCompatVersion.SMDIFFER:
        from reviewboard.diffviewer.smdiff import SMDiffer
        cls = SMDiffer
    else:
        raise DiffCompatError(
            'Invalid diff compatibility version (%s) passed to Differ' %
            compat_version)

    return cls(a, b, ignore_space, compat_version=compat_version)
