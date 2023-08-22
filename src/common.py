"""
Common utility functions.
"""

from gi.repository import GObject


def disallow_nonnumeric(self, entry, text, length, position, *args):
    """
    Handler for GtkEditable insert-text call that only allows numeric
    values to be entered.
    """
    if not text:
        return
    if not text.isdigit():
        GObject.signal_stop_emission_by_name(entry, 'insert-text')


def find_in_stringlist(model, item: str):
    """
    Gets the position of an item in the StringList, or None if not found.
    Replacement for .find function in models that don't have it.
    """
    i = 0
    while True:
        found = model.get_item(i)
        if not found:
            break
        if found.get_string() == item:
            return i
        i += 1
    return None
