# -*- coding: utf-8 -*-
# config_store module - version v2
# Change log (last change first):
#   v2 - Code audit (Link Clash v14): write_json swaps the new file in with one call (File.Replace), so there is
#        never a moment with no file; its temporary file has a name of its own, so two people saving a shared
#        file at once can't write into the same temporary file.
#   v1 - Code consolidation step 7 (Auto Conduit - Config v3): where the tools' settings files live, the office
#        defaults and the safe write, shared by clash_rules, slc_addressing, nac_voice_types, slc_riser and
#        mounting_rules.
"""Where the tools' settings files are kept, and how they are read and written. Check here before a config gets
file handling of its own.

Each user's settings   %APPDATA%\\pyRevit\\EWTestSuite\\<file> (USER_DIR). pyRevit updates never touch it.
                       (Address SLC keeps its table in %APPDATA%\\MyTools, shared with the standalone add-in.)
Office defaults        config\\<name>.default.json, in the repository. A user who has no settings file yet starts
                       from a copy of it, when it exists.
Shared file            a config's *_PATH setting (a network path) is used instead of the user's own file; no
                       default is copied to it.

user_file(name, override, folder)   the file a config reads and writes
default_file(name)                  an office default in config\\
read_json(path, empty)              the file's contents; `empty` if it is missing or blank; raises if unreadable
write_json(path, data)              writes safely: to a temporary file, then swapped in; creates the folder
start_from(path, sources)           the first time (path doesn't exist yet): copies the first source that exists
"""
import json
import os
import random
import shutil

EXTENSION_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(EXTENSION_DIR, "config")
APPDATA_DIR = os.getenv("APPDATA") or os.path.expanduser("~")
USER_DIR = os.path.join(APPDATA_DIR, "pyRevit", "EWTestSuite")


def user_file(name, override=None, folder=None):
    """The settings file to use: override (a shared path) if set, else <folder, or USER_DIR>\\name."""
    return override or os.path.join(folder or USER_DIR, name)


def default_file(name):
    """An office default kept in the repository's config folder, e.g. default_file("clash_rules.default.json")."""
    return os.path.join(CONFIG_DIR, name)


def read_json(path, empty=None):
    """The file's contents, or `empty` when the file is missing or blank. Raises if it can't be read, so a broken
    file is never mistaken for an empty one (and then overwritten)."""
    if not os.path.isfile(path):
        return empty
    with open(path, "r") as f:
        text = f.read()
    if not text.strip():
        return empty
    return json.loads(text)


def write_json(path, data, indent=2):
    """Write data to path, creating the folder if needed. Written in full to a temporary file first and then
    swapped in, so a failed write never leaves a half-written or missing settings file. Raises if it can't be
    written."""
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    tmp = "%s.%08x.tmp" % (path, random.getrandbits(32))    # its own name: two saves at once never share one
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=indent, sort_keys=True)
        _swap_in(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def _swap_in(tmp, path):
    """Put the finished temporary file in place of path."""
    if not os.path.exists(path):
        os.rename(tmp, path)
        return
    try:
        from System.IO import File          # in Revit: one call that replaces the file (Windows ReplaceFile)
        File.Replace(tmp, path, None)
        return
    except ImportError:
        pass
    except Exception:
        pass                                # e.g. a network drive that can't replace files: the older way below
    if hasattr(os, "replace"):
        os.replace(tmp, path)               # outside Revit (Python 3)
        return
    os.remove(path)
    os.rename(tmp, path)


def start_from(path, sources):
    """When path doesn't exist yet, copy the first of sources that exists to it (an older location of the file,
    or an office default). Returns the source copied, or None. Never raises: a bad source just means the
    settings start empty."""
    if os.path.exists(path):
        return None
    for src in sources:
        try:
            if src and os.path.isfile(src):
                folder = os.path.dirname(path)
                if folder and not os.path.isdir(folder):
                    os.makedirs(folder)
                shutil.copyfile(src, path)
                return src
        except Exception:
            pass
    return None
