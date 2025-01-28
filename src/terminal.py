# SPDX-License-Identifier: MIT

from gi.repository import GLib, Gdk, Gtk, Vte

@Gtk.Template(resource_path="/com/github/knuxify/SerialConsole/ui/terminal.ui")
class SerialTerminal(Vte.Terminal):
    """
    VTE terminal subclass that handles copy/paste.

    Actual serial logic is handled in window.py.
    """
    __gtype_name__ = "SerialTerminal"

    def __init__(self):
        super().__init__()

        self.install_action("term.copy", None, self.copy_activated)
        self.action_set_enabled("term.copy", False)
        self.install_action("term.paste", None, self.paste_activated)
        self.install_action("term.select-all", None, self.select_all_activated)
        self.install_action("term.reset", None, self.reset_activated)

    @Gtk.Template.Callback()
    def selection_changed(self, *args):
        self.action_set_enabled("term.copy", self.get_has_selection())

    # Copy to clipboard
    def copy_activated(self, *args):
        clipboard = self.get_clipboard()
        clipboard.set(self.get_text_selected(Vte.Format.TEXT))

    # Clipboard paste
    def paste_callback(self, source, result, *args):
        try:
            text = source.read_text_finish(result)
        except GLib.GError:
            import traceback
            traceback.print_exc()
            return

        self.paste_text(text)

    def paste_activated(self, *args):
        clipboard = self.get_clipboard()
        clipboard.read_text_async(None, self.paste_callback, None)

    # Select all
    def select_all_activated(self, *args):
        self.select_all()

    # Reset terminal
    def reset_activated(self, *args):
        self.reset(True, True)
