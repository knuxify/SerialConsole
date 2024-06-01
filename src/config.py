"""
Shim for global config access.
"""

from gi.repository import Gio, Gtk
from enum import IntEnum

config = Gio.Settings.new("com.github.knuxify.SerialConsole")
enums = {}

# GSettings enum handlers


def get_enum_for_key(key, enum_name) -> IntEnum:
    """Takes a key name from the config and returns an Enum for it."""
    global config
    global enums
    key = config.props.settings_schema.get_key(key)
    enum_strs = key.get_range().unpack()[1]
    converted_enum_strs = [
        s.upper().replace("(", "").replace(")", "").replace("/", "_").replace(" ", "_")
        for s in enum_strs
    ]
    result = IntEnum(enum_name, converted_enum_strs, start=0)
    enums[result] = enum_strs
    return result


def to_enum_str(enum, value):
    """
    Takes an enum generated with get_enum_for_key and an ID value
    and returns the enum string for the value.
    """
    return enums[enum][value]


def from_enum_str(enum, value):
    """
    Takes an enum generated with get_enum_for_key and a string value
    and returns the ID for the value.
    """
    return enums[enum].index(value)


def enum_to_stringlist(enum):
    """
    Takes an enum generated with get_enum_for_key and returns
    a GtkStringList containing its items.
    """
    return Gtk.StringList.new(enums[enum])


Parity = get_enum_for_key("parity", "Parity")
FlowControl = get_enum_for_key("flow-control", "FlowControl")
