# -*- coding: utf-8 -*-
# config_store module - version v1
# Change log (last change first):
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
    """Write data to path, creating the folder if needed. Written to a temporary file first and then swapped in,
    so a failed write never leaves a half-written settings file. Raises if it can't be written."""
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=indent, sort_keys=True)
    if os.path.exists(path):
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
