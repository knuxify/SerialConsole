"""
Contains code for handling the serial device.
"""

from gi.repository import GLib, GObject
import serial
import time
import threading

from .config import Parity

REFRESH_INTERVAL = 0.2  # in seconds

class SerialHandler(GObject.Object):
    """
    Wrapper around a serial device. Handles *one* serial console
    and its settings, as well as its I/O.
    """

    def __init__(self):
        super().__init__()
        self.serial = serial.Serial()
        self._serial_loop_running = False
        self._stop_serial_loop = False
        self._connection_lost = False
        self._force_close = False

    @GObject.Property(type=str)
    def port(self):
        return self.serial.port

    @port.setter
    def port(self, value):
        self.serial.port = value

    @GObject.Property(type=int)
    def baud_rate(self):
        return self.serial.baudrate

    @baud_rate.setter
    def baud_rate(self, value):
        self.serial.baudrate = value

    @GObject.Property(type=int)
    def data_bits(self):
        bits = self.serial.bytesize
        match bits:
            case serial.FIVEBITS: return 5
            case serial.SIXBITS: return 6
            case serial.SEVENBITS: return 7
            case serial.EIGHTBITS: return 8

    @data_bits.setter
    def data_bits(self, value):
        match value:
            case 5: self.serial.bytesize = serial.FIVEBITS
            case 6: self.serial.bytesize = serial.SIXBITS
            case 7: self.serial.bytesize = serial.SEVENBITS
            case 8: self.serial.bytesize = serial.EIGHTBITS
            case _:
                raise ValueError

    @GObject.Property(type=int)
    def parity(self):
        match self.serial.parity:
            case serial.PARITY_NONE:  p = Parity.NONE
            case serial.PARITY_EVEN:  p = Parity.EVEN
            case serial.PARITY_ODD:   p = Parity.ODD
            case serial.PARITY_MARK:  p = Parity.MARK
            case serial.PARITY_SPACE: p = Parity.SPACE

        return p

    @parity.setter
    def parity(self, value):
        match int(value):
            case Parity.NONE:  p = serial.PARITY_NONE
            case Parity.EVEN:  p = serial.PARITY_EVEN
            case Parity.ODD:   p = serial.PARITY_ODD
            case Parity.MARK:  p = serial.PARITY_MARK
            case Parity.SPACE: p = serial.PARITY_SPACE

        self.serial.parity = p

    @GObject.Property(type=bool, default=False, flags=GObject.ParamFlags.READABLE)
    def is_open(self):
        return self.serial.is_open

    def open(self):
        """Opens the serial port."""
        self._force_close = False
        self.serial.open()
        self.serial_loop_start()
        self.notify('is-open')

    def close(self):
        """Closes the serial port."""
        self.serial.close()
        self.serial_loop_stop()
        self.notify('is-open')

    def write_text(self, text: str):
        """
        Writes UTF-8 text (as returned by VteTerminal::commit) to the
        serial device.
        """
        self.serial.write(text.encode('utf-8'))

    # Read loop handlers.
    # pyserial has no async handler, so reads must be done sequentially
    # every few seconds.

    @GObject.Signal()
    def device_busy(self):
        """
        Emitted when the opened device is busy (i.e. used by another
        program).
        """
        pass

    @GObject.Signal(arg_types=(GLib.Bytes, ))
    def read_done(self, data: GLib.Bytes):
        """Notifies consumer about a read on the serial device."""
        pass

    def serial_loop(self):
        self._connection_lost = False
        self._serial_loop_running = True
        data = None
        while not self._stop_serial_loop:
            try:
                data = self.serial.read()
            except TypeError:  # Serial was closed
                break
            except serial.serialutil.SerialException as e:
                msg = str(e)
                if '9' in msg:  # Serial was closed mid-read
                    break
                elif '16' in msg:  # Resource busy
                    GLib.idle_add(self.emit, 'device_busy')
                    break
                # Connection has been lost
                self.serial.close()
                self._connection_lost = True
                break

            if data:
                GLib.idle_add(self.emit, 'read_done', GLib.Bytes.new_take(data))

        GLib.idle_add(self.notify, 'is-open')
        self._serial_loop_running = False

    def serial_loop_start(self):
        if self._serial_loop_running:
            return False

        self._loop_read_queue = []
        self._serial_loop_thread = threading.Thread(target=self.serial_loop, daemon=True)
        self._serial_loop_thread.start()

    def serial_loop_stop(self):
        self._stop_serial_loop = True
        while self._serial_loop_running:
            time.sleep(0.5)
        self._stop_serial_loop = False
        self._serial_loop_thread = None
