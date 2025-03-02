"""
Main code for the application window.
"""

from gi.repository import Adw, Gio, GLib, GObject, Gtk, Vte  # noqa: F401
import serial.tools.list_ports
from typing import Optional
import os.path

from . import DEVEL
from .config import (
    config,
    Parity,
    FlowControl,
    to_enum_str,
    from_enum_str,
    enum_to_stringlist,
)
from .common import (
    disallow_nonnumeric,
    find_in_stringlist,
    copy_list_to_stringlist,
    BoolPropertyAction,
)
from .serial import SerialHandler, SerialHandlerState
from .terminal import SerialTerminal  # noqa: F401
from .logger import SerialLogger, DEFAULT_LOG_FILENAME


# PCRE flags for search regex:
PCRE2_CASELESS = 0x00000008
PCRE2_MULTILINE = 0x00000400


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

    search_bar = Gtk.Template.Child()
    search_entry = Gtk.Template.Child()
    search_settings_button = Gtk.Template.Child()
    search_settings_menu = Gtk.Template.Child()
    search_next_button = Gtk.Template.Child()
    search_previous_button = Gtk.Template.Child()

    # Search properties

    search_case_sensitive = GObject.Property(type=bool, default=False)
    search_regex = GObject.Property(type=bool, default=False)

    @GObject.Property(type=bool, default=True)
    def search_wrap_around(self):
        return self.terminal.search_get_wrap_around()

    @search_wrap_around.setter
    def search_wrap_around(self, search_wrap_around: bool):
        return self.terminal.search_set_wrap_around(search_wrap_around)

    # Search properties end

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reconnect_thread = None

        if DEVEL:
            self.add_css_class("devel")

        application = self.get_application()

        # Set up terminal style
        application.get_style_manager().connect(
            "notify::dark", self.theme_change_callback
        )
        self.set_terminal_color_scheme()

        # Set up search bar
        self.search_bar.connect_entry(self.search_entry)
        self.install_action("win.find", None, self.toggle_search_bar)
        self.terminal.search_set_wrap_around(True)
        self.prev_search_query: Optional[str] = None

        for cfg in ("search-wrap-around", "search-case-sensitive", "search-regex"):
            config.bind(cfg, self, cfg, flags=Gio.SettingsBindFlags.DEFAULT)

            # HACK: Properties installed with install_action/install_property_action
            # are unusable in any of the action-name options of buttons, menus, etc.
            # We have to use a custom class for the action to automate binding to a
            # property.
            action = BoolPropertyAction(cfg.replace("search-", "search."), self, cfg)
            self.add_action(action)

            self.connect(f"notify::{cfg}", self.search_changed)

        # Set up serial handler
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

        # Set up logger
        self.logger = SerialLogger(self.serial)
        self.logger.connect("log-open-failure", self.on_log_open_failure)

        # Miscelaneous app setup
        self.set_icon_name(application.get_application_id())

        self.connect("close-request", self.on_close)

        self.handle_state_change(self.serial)

    def on_maximize_toggle(self, action, value):
        action.set_value(value)
        if value.get_boolean():
            self.maximize()
        else:
            self.unmaximize()

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
        # Update terminal's connection status
        self.terminal.props.connected = state == SerialHandlerState.OPEN

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
        # TRANSLATORS: {msg} is a placeholder for the message, do not modify
        # the string between the braces!
        error_message = _("A connection error has occured: {msg}").format(msg=message)

        if errno == 13:
            error_message = _(
                # TRANSLATORS: {port} is a placeholder for the port name, do not modify
                # the string between the braces!
                'Permission denied for port {port}; make sure you\'re in the "tty" group'
            ).format(port=serial.port)
        elif errno == 16:
            error_message = _(
                # TRANSLATORS: {port} is a placeholder for the port name, do not modify
                # the string between the braces!
                "Serial port {port} is busy; make sure no other application is using it"
            ).format(port=serial.port)

        self.toast_overlay.add_toast(Adw.Toast.new(error_message))

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
        if not self.terminal.props.connected:
            self.terminal.feed(bytes("\a", "utf-8"))
            return
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

        if (
            self.terminal.get_text()[0] is None
            or not self.terminal.get_text()[0].strip()
        ):
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

    # Search function
    def toggle_search_bar(self, *args):
        self.search_bar.props.search_mode_enabled = (
            not self.search_bar.props.search_mode_enabled
        )

    @Gtk.Template.Callback()
    def search_changed(self, *args):
        flags = PCRE2_MULTILINE

        query = self.search_entry.get_text()
        self.search_next_button.props.sensitive = not not query
        self.search_previous_button.props.sensitive = not not query

        if not self.props.search_case_sensitive:
            query = query.lower()
            flags |= PCRE2_CASELESS

        if not self.props.search_regex:
            query = GLib.Regex.escape_string(query, len(query))

        try:
            regex = Vte.Regex.new_for_search(query, len(query), flags)
        except GLib.Error:
            self.search_entry.add_css_class("error")
            self.prev_search_query = query
            return
        else:
            self.search_entry.remove_css_class("error")

        # Jump to searched query; code adapted from gnome-console
        narrowing_down = self.prev_search_query and query in self.prev_search_query
        if not narrowing_down:
            self.terminal.search_find_previous()

        self.terminal.search_set_regex(regex, 0)

        if narrowing_down:
            self.terminal.search_find_previous()
        self.terminal.search_find_next()

        self.prev_search_query = query

    @Gtk.Template.Callback()
    def search_previous(self, *args):
        self.terminal.search_find_previous()

    @Gtk.Template.Callback()
    def search_next(self, *args):
        self.terminal.search_find_next()


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
    log_path_row = Gtk.Template.Child()

    def __init__(self):
        super().__init__()
        self._ignore_port_change = False
        self._needs_setup = True
        self.custom_scrollback_spinbutton.set_range(0, 10000000)
        self.custom_scrollback_spinbutton.set_increments(100, 1000)

        # Only allow numbers to be typed into custom baud rate field
        self.custom_baudrate.set_input_purpose(Gtk.InputPurpose.DIGITS)
        self.custom_baudrate.get_delegate().connect("insert-text", disallow_nonnumeric)

        self._log_path_dialog = Gtk.FileDialog.new()
        self._log_path_dialog.props.initial_name = DEFAULT_LOG_FILENAME
        self._log_path_dialog.set_initial_folder(
            Gio.File.new_for_path(
                GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)
            )
        )
        self._log_path_dialog.props.modal = True

        # Set default value for log-path
        if config["log-path"] == "":
            config["log-path"] = os.path.join(
                GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS),
                DEFAULT_LOG_FILENAME,
            )

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
        self.serial.connect("notify::state", lambda *args: self.notify("port-display"))

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
                "notify::" + property,
                lambda *args, prop=property: self.notify(prop + "-str"),
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

        config.bind(
            "log-path",
            self.log_path_row,
            "subtitle",
            flags=Gio.SettingsBindFlags.DEFAULT,
        )

        self.log_path_row.set_subtitle(config["log-path"])

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

    @Gtk.Template.Callback()
    def show_log_path_chooser(self, *args):
        self._log_path_dialog.save(
            self.get_native(), None, self.set_log_path_from_chooser, None
        )

    def set_log_path_from_chooser(
        self, dialog: Gtk.FileDialog, result: Gio.AsyncResult, *args
    ):
        try:
            response: Optional[Gio.File] = dialog.save_finish(result)
        except GLib.Error:
            return

        if response is None:
            return

        config["log-path"] = response.get_path()

    @Gtk.Template.Callback()
    def open_log_file(self, *args):
        """Opens the log file in the default text editor."""
        Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(config["log-path"]))

    @Gtk.Template.Callback()
    def reset_console(self, *args):
        self.get_native().terminal.reset_activated()
