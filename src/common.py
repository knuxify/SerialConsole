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
    Gets the position of an item in the StringList, or -1 if not found.
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
    return -1


def copy_list_to_stringlist(target: list, model):
    """
    Updates the model to match the input list. Assumes list has no duplicates.
    """
    model_conv = [p.get_string() for p in model]

    target_set = set(target)
    model_set = set(model_conv)

    if target_set == model_set:
        # Both lists are the same, no operation needed
        return

    added = target_set - model_set
    removed = model_set - target_set

    # TODO: Add efficient chunk splice mechanism. Since in our case,
    # we will likely be adding/removing only one item at a time, anything
    # fancier is unnecessary for now.

    for item in removed:
        model.remove(find_in_stringlist(model, item))

    for item in [i for i in target if i in added]:  # ensures order
        model.splice(target.index(item), 0, [item])
