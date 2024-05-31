"""
Contains code for handling the serial device.
"""

from gi.repository import GLib, GObject, Gio
import os

from .config import config
from .serial import SerialHandlerState

class SerialLogger(GObject.Object):
    """Handles logging for the serial file."""

    def __init__(self, serial):
        super().__init__()
        self._file = None

        self.serial = serial
        self.serial.connect("read_done", self.serial_read)
        self.serial.connect("notify::state", self.start_flush_timeout)

        config.bind("log-path", self, "log-path", flags=Gio.SettingsBindFlags.DEFAULT)
        config.connect("changed::log-binary", self.reopen_log)

    @GObject.Signal
    def log_open_failure(self):
        pass

    @GObject.Property(type=str)
    def log_path(self):
        return self._path

    @log_path.setter
    def log_path(self, value):
        self._path = value
        if not value:
            self.close_log()
            return

        if not os.path.exists(value):
            basedir = os.path.dirname(value)
            if not os.path.exists(basedir):
                try:
                    os.makedirs(basedir)
                except:  # noqa: E722
                    self.emit("log-open-failure")
                    return

        if os.path.isdir(value):
            self.emit("log-open-failure")
            return

        self.close_log()
        self.open_log()

    def serial_read(self, serial, data, *args):
        if self._file:
            if config["log-binary"]:
                self._file.write(data.get_data())
            else:
                try:
                    self._file.write(data.get_data().decode("utf-8"))
                except UnicodeDecodeError:
                    self._file.write("�")

    def write_text(self, text):
        """Writes text to the log file."""
        if self._file:
            if config["log-binary"]:
                self._file.write(bytes(text, "utf-8"))
            else:
                self._file.write(text)

    def flush_log(self, *args):
        """Flushes the logfile."""
        if self._file:
            try:
                self._file.flush()
            except ValueError:
                pass
        return self.serial.state == SerialHandlerState.CLOSED

    def open_log(self):
        """Opens the logfile."""
        try:
            if config["log-binary"]:
                self._file = open(self._path, "a+b")
            else:
                self._file = open(self._path, "a+")
        except:  # noqa: E722
            self.emit("log-open-failure")
            return

    def close_log(self, *args):
        """Closes the logfile."""
        if self._file:
            self.flush_log()
            self._file.close()
            self._file = None

    def reopen_log(self, *args):
        if self._file:
            self.close_log()
            self.open_log()

    def start_flush_timeout(self, *args):
        if self.serial.state == SerialHandlerState.OPEN:
            GLib.timeout_add(1000, self.flush_log)
