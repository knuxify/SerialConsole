"""
Main code for the application window.
"""

from gi.repository import Adw, Gio, GLib, GObject, Gtk, Vte  # noqa: F401
import serial.tools.list_ports
import time
import threading

from .config import (
    config,
    Parity,
    FlowControl,
    to_enum_str,
    from_enum_str,
    enum_to_stringlist,
)
from .common import disallow_nonnumeric, find_in_stringlist, copy_list_to_stringlist
from .serial import SerialHandler, SerialHandlerState
from .terminal import SerialTerminal  # noqa: F401
from .logger import SerialLogger


@Gtk.Template(resource_path="/com/github/knuxify/SerialConsole/ui/window.ui")
class SerialConsoleWindow(Adw.ApplicationWindow):
    __gtype_name__ = "SerialConsoleWindow"

    split_view = Gtk.Template.Child()
    sidebar = Gtk.Template.Child()
    terminal = Gtk.Template.Child()

    open_button_switcher = Gtk.Template.Child()
    open_button = Gtk.Template.Child()
    close_button = Gtk.Template.Child()

    reconnecting_banner = Gtk.Template.Child()
    toast_overlay = Gtk.Template.Child()

    console_header = Gtk.Template.Child()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reconnect_thread = None

        self.get_application().get_style_manager().connect(
            "notify::dark", self.theme_change_callback
        )
        self.set_terminal_color_scheme()

        self.serial = SerialHandler()
        self.serial.connect("read_done", self.terminal_read)
        self.serial.connect("notify::state", self.handle_state_change)
        self.serial.connect("error", self.handle_error)
        self.sidebar.reconnect_automatically.bind_property(
            "active",
            self.serial,
            "reconnect-automatically",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )

        self.ports = Gtk.StringList()
        self.get_available_ports()
        GLib.timeout_add(1000, self.get_available_ports)

        self.logger = SerialLogger(self.serial)
        self.logger.connect("log-open-failure", self.on_log_open_failure)

        self.connect("close-request", self.on_close)

        self.handle_state_change(self.serial)

    def on_close(self, *args):
        self.serial.close()
        self.logger.close_log()

    def on_log_open_failure(self, *args):
        self.sidebar.log_enable_toggle.set_active(False)
        self.toast_overlay.add_toast(
            Adw.Toast.new(
                _("Failed to open log file for writing; check the path and try again")
            )
        )

    # Port update functions

    def get_available_ports(self, *args):
        ports = sorted([port[0] for port in serial.tools.list_ports.comports()])
        self.sidebar._ignore_port_change = True
        copy_list_to_stringlist(ports, self.ports)
        self.sidebar._ignore_port_change = False
        try:
            self.sidebar.port_selector.set_selected(
                find_in_stringlist(self.ports, self.serial.port)
            )
        except (TypeError, ValueError, OverflowError):
            pass

        if not self.serial.port and ports:
            self.serial.port = ports[0]

        if self.serial.state == SerialHandlerState.CLOSED:
            self.open_button.set_sensitive(bool(ports))

        return True

    def handle_state_change(self, serial, *args):
        state = serial.props.state

        # Toggle "reconnecting" banner
        self.reconnecting_banner.set_revealed(state == SerialHandlerState.RECONNECTING)
        # Toggle terminal sensitivity
        self.terminal.props.sensitive = (state == SerialHandlerState.OPEN)

        # Update open button
        if state != SerialHandlerState.CLOSED:
            self.open_button.set_sensitive(False)
            self.close_button.set_sensitive(True)
            self.open_button_switcher.set_visible_child(self.close_button)
        else:
            self.open_button.set_sensitive(bool(self.ports.get_n_items()))
            self.close_button.set_sensitive(False)
            self.open_button_switcher.set_visible_child(self.open_button)

    def handle_error(self, serial, errno: int, message: str):
        if errno == 16:
            self.toast_overlay.add_toast(
                Adw.Toast.new(
                    _("Serial port {port} is busy; make sure no other application is using it").format(port=serial.port)
                )
            )
        else:
            self.toast_overlay.add_toast(
                Adw.Toast.new(
                    _("A connection error has occured: {msg}").format(msg=messsage)
                )
            )

    @Gtk.Template.Callback()
    def open_serial(self, *args):
        self.open_button.set_sensitive(False)
        self.serial.open()

    @Gtk.Template.Callback()
    def close_serial(self, *args):
        self.serial._force_close = True
        self.close_button.set_sensitive(False)
        self.serial.close()

    # Console handling functions

    @Gtk.Template.Callback()
    def open_sidebar(self, *args):
        self.split_view.props.show_sidebar = True

    @Gtk.Template.Callback()
    def close_sidebar(self, *args):
        self.split_view.props.show_sidebar = False

    @Gtk.Template.Callback()
    def terminal_commit(self, terminal, text, size, *args):
        """Get input from the terminal and send it over serial."""
        if config["echo"]:
            self.terminal.feed(bytes(text, "utf-8"))
            self.logger.write_text(text)
        self.serial.write_text(text)

    def terminal_read(self, serial, data, *args):
        self.terminal.feed(data.get_data())

    def terminal_write_message(self, text):
        """Writes an info message to the terminal."""
        if config["disable-info-messages"]:
            return

        if not self.terminal.get_text()[0].strip():
            self.terminal.feed(bytes(f"\r\033[0;90m--- {text} ---\r\n\033[0m", "utf-8"))
        else:
            self.terminal.feed(
                bytes(f"\r\n\033[0;90m--- {text} ---\r\n\033[0m", "utf-8")
            )

        self.logger.write_text(f"\r\n--- {text} ---")

    def set_terminal_color_scheme(self, *args):
        """Sets up a terminal color scheme from the default colors."""
        style = self.get_style_context()
        bg = style.lookup_color("view_bg_color")[1]
        fg = style.lookup_color("view_fg_color")[1]
        self.terminal.set_color_background(bg)
        self.terminal.set_color_foreground(fg)

    # When the 'dark' property on the style manager is changed, the
    # stylesheet for the new mode has not yet been loaded. Turns out,
    # running the change function through GLib.idle_add is enough to
    # reload it once everything's done loading.

    def theme_change_callback(self, *args):
        GLib.idle_add(self.set_terminal_color_scheme)


@Gtk.Template(resource_path="/com/github/knuxify/SerialConsole/ui/settings-pane.ui")
class SerialConsoleSettingsPane(Gtk.Box):
    __gtype_name__ = "SerialConsoleSettingsPane"

    reconnect_automatically = Gtk.Template.Child()

    port_selector = Gtk.Template.Child()
    baudrate_selector = Gtk.Template.Child()
    custom_baudrate = Gtk.Template.Child()

    data_bits_selector = Gtk.Template.Child()
    parity_selector = Gtk.Template.Child()
    stop_bits_selector = Gtk.Template.Child()
    flow_control_selector = Gtk.Template.Child()

    custom_scrollback_spinbutton = Gtk.Template.Child()
    unlimited_scrollback_toggle = Gtk.Template.Child()
    disable_info_messages_toggle = Gtk.Template.Child()
    local_echo_toggle = Gtk.Template.Child()

    log_enable_toggle = Gtk.Template.Child()
    log_path_entry = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self._ignore_port_change = False
        self._needs_setup = True
        self.custom_scrollback_spinbutton.set_range(0, 10000000)
        self.custom_scrollback_spinbutton.set_increments(100, 1000)

        # Only allow numbers to be typed into custom baud rate field
        self.custom_baudrate.set_input_purpose(Gtk.InputPurpose.DIGITS)
        self.custom_baudrate.get_delegate().connect("insert-text", disallow_nonnumeric)

        self.connect("realize", self._setup)

    def _setup(self, *args):
        """
        get_native returns NULL before the window is fully displayed,
        so we need to do setup then.
        """
        if not self._needs_setup:
            return

        self.serial = self.get_native().serial

        self.ports = self.get_native().ports
        self.port_selector.set_model(self.ports)

        title = self.get_native().console_header.get_title_widget()
        self.bind_property(
            "port_display",
            title,
            "subtitle",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )
        self.serial.connect("notify::port", lambda *args: self.notify("port-display"))
        self.serial.connect(
            "notify::state", lambda *args: self.notify("port-display")
        )

        self.setup_settings_bindings()

        self._needs_setup = False

    @GObject.Property(type=str)
    def port_display(self):
        if self.serial.state != SerialHandlerState.CLOSED:
            return self.serial.port

        # TRANSLATORS: Default window caption when no console is connected
        return _("(Not connected)")

    def setup_settings_bindings(self):
        config.bind(
            "reconnect-automatically",
            self.reconnect_automatically,
            "active",
            flags=Gio.SettingsBindFlags.DEFAULT,
        )

        # baud-rate is not included here, as its selector is set up separately.
        # We don't do bindings here since each selector has its own "set from
        # selector" function (and it wouldn't be possible since we need to
        # convert from string to int first anyways).
        params = {
            "port": ("selector", self.port_selector),
            "data-bits": ("selector", self.data_bits_selector),
            "stop-bits": ("selector", self.stop_bits_selector),
        }

        # Serial parameters are directly synced to config:
        for property in ("port", "baud-rate", "data-bits", "stop-bits"):

            if property == "port":
                # For ports, there is no guarantee that the last used
                # port will be available, so we set the available port
                # if and only if it's actually available; otherwise we
                # get the first item in the model.
                ports = [p.get_string() for p in self.get_native().ports]
                if config["port"] in ports:
                    port = config["port"]
                elif ports:
                    port = ports[0]
                    config["port"] = port
                else:
                    port = ""
                    config["port"] = port
                self.serial.port = port
            else:
                self.serial.set_property(property, config[property])

            config.bind(
                property, self.serial, property, flags=Gio.SettingsBindFlags.DEFAULT
            )

            if property in params:
                if params[property][0] == "selector":
                    selector = params[property][1]
                    i = find_in_stringlist(selector.get_model(), str(config[property]))
                    if i < 0:
                        i = 0
                    selector.set_selected(i)

        # Enum properties need to be handled separately, else they
        # end up syncing the *strings*, not the *IDs*:
        enums = {
            "parity": (Parity, self.parity_selector),
            "flow-control": (FlowControl, self.flow_control_selector),
        }

        for property in ("parity", "flow-control"):
            self.serial.set_property(property, config.get_enum(property))

            config.bind(
                property, self, property + "-str", flags=Gio.SettingsBindFlags.DEFAULT
            )

            selector = enums[property][1]
            selector.set_model(enum_to_stringlist(enums[property][0]))
            selector.bind_property(
                "selected", self.serial, property, GObject.BindingFlags.BIDIRECTIONAL
            )
            selector.set_selected(config.get_enum(property))
            self.serial.connect(
                "notify::" + property, lambda *args: self.notify(property + "-str")
            )

        # Set up baud rate selector
        baudrate_model = self.baudrate_selector.get_model()
        for i in range(baudrate_model.get_n_items()):
            rate = baudrate_model.get_item(i).get_string()
            try:
                if int(rate) == config["baud-rate"]:
                    self.baudrate_selector.set_selected(i)
                    break
            except ValueError:  # custom
                self.custom_baudrate.set_text(str(config["baud-rate"]))
                self.baudrate_selector.set_selected(i)

        # Terminal settings
        config.bind(
            "scrollback",
            self.custom_scrollback_spinbutton,
            "value",
            flags=Gio.SettingsBindFlags.DEFAULT,
        )
        config.bind(
            "unlimited-scrollback",
            self.unlimited_scrollback_toggle,
            "active",
            flags=Gio.SettingsBindFlags.DEFAULT,
        )
        self.custom_scrollback_spinbutton.connect(
            "value-changed", self.update_scrollback_from_pane
        )
        self.unlimited_scrollback_toggle.connect(
            "notify::active", self.update_scrollback_from_pane
        )
        self.update_scrollback_from_pane()

        config.bind(
            "disable-info-messages",
            self.disable_info_messages_toggle,
            "active",
            flags=Gio.SettingsBindFlags.DEFAULT,
        )

        config.bind(
            "echo",
            self.local_echo_toggle,
            "active",
            flags=Gio.SettingsBindFlags.DEFAULT,
        )

        # Logging settings
        config.bind(
            "log-enable",
            self.log_enable_toggle,
            "active",
            flags=Gio.SettingsBindFlags.DEFAULT,
        )

        self.log_path_entry.set_text(config["log-path"])
        self.log_path_entry.connect("apply", self.set_log_path_from_pane)

    def set_log_path_from_pane(self, *args):
        config["log-path"] = self.log_path_entry.get_text()

    def update_scrollback_from_pane(self, *args):
        if config["unlimited-scrollback"]:
            self.get_native().terminal.set_scrollback_lines(-1)
        else:
            self.get_native().terminal.set_scrollback_lines(config["scrollback"])

    @GObject.Property(type=str)
    def parity_str(self):
        """Workaround to allow us to sync settings."""
        return to_enum_str(Parity, self.serial.parity)

    @parity_str.setter
    def parity_str(self, value):
        self.serial.parity = from_enum_str(Parity, value)

    @GObject.Property(type=str)
    def flow_control_str(self):
        """Workaround to allow us to sync settings."""
        return to_enum_str(FlowControl, self.serial.flow_control)

    @flow_control_str.setter
    def flow_control_str(self, value):
        self.serial.flow_control = from_enum_str(FlowControl, value)

    @Gtk.Template.Callback()
    def set_port_from_selector(self, selector, *args):
        if self._needs_setup or self._ignore_port_change:
            return

        try:
            port = selector.get_selected_item().get_string()
        except AttributeError:
            return
        if port == self.serial.port:
            return
        self.serial.port = port

        _switched_port_text = _("switched port to {port}").format(port=port)
        self.get_native().terminal_write_message(_switched_port_text)

    @Gtk.Template.Callback()
    def set_baudrate_from_selector(self, *args):
        # This is called for both the selector and updates on the custom
        # baudrate, so we ignore the passed selector value.
        try:
            baudrate = int(self.baudrate_selector.get_selected_item().get_string())
            self.custom_baudrate.set_visible(False)
        except ValueError:  # selected rate is a string, so Custom
            self.custom_baudrate.set_visible(True)
            try:
                baudrate = int(self.custom_baudrate.get_text())
            except ValueError:  # baudrate is empty
                baudrate = 0
        self.serial.baud_rate = baudrate

    @Gtk.Template.Callback()
    def set_data_bits_from_selector(self, selector, *args):
        self.serial.data_bits = int(selector.get_selected_item().get_string())

    @Gtk.Template.Callback()
    def set_stop_bits_from_selector(self, selector, *args):
        self.serial.stop_bits = int(selector.get_selected_item().get_string())
