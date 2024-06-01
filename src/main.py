# SPDX-License-Identifier: MIT
# (c) 2023 knuxify and Ear Tag contributors

import sys
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Vte", "3.91")

from gi.repository import Adw, Gtk, Gio  # noqa: E402

from .window import SerialConsoleWindow  # noqa: E402


class Application(Adw.Application):
    def __init__(self, version="dev"):
        super().__init__(
            application_id="com.github.knuxify.SerialConsole",
            resource_base_path="/com/github/knuxify/SerialConsole",
            flags=Gio.ApplicationFlags.HANDLES_OPEN,
        )
        self.version = version
        self.connect("open", self.do_activate)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = SerialConsoleWindow(application=self)
        self.create_action("about", self.on_about_action, None)
        self.create_action("quit", self.on_quit_action, "<Ctrl>q")

        win.present()
        self._ = _

    def create_action(self, name, callback, accel=None):
        """Add an Action and connect to a callback"""
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if accel:
            self.set_accels_for_action(f"app.{name}", (accel, None))
        return action

    def on_about_action(self, widget, _):
        about = Adw.AboutDialog(
            application_name="Serial Console",
            application_icon="com.github.knuxify.SerialConsole",
            developers=["knuxify"],
            license_type=Gtk.License.MIT_X11,
            issue_url="https://github.com/knuxify/serialconsole",
            version=self.version,
            website="https://github.com/knuxify/serialconsole",
        )

        if self._("translator-credits") != "translator-credits":
            # TRANSLATORS: Add your name/nickname here
            about.props.translator_credits = self._("translator-credits")

        about.present(self.props.active_window)

    def on_quit_action(self, *args):
        win = self.props.active_window
        win.close()


def main(version):
    app = Application(version)
    return app.run(sys.argv)
