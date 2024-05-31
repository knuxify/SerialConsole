"""
Contains code for handling the serial device.
"""

from gi.repository import GLib, GObject
import serial
import time
import traceback
import threading

from .config import Parity, FlowControl

REFRESH_INTERVAL = 0.2  # in seconds


class SerialHandlerState:
    RECONNECTING = -1
    CLOSED = 0
    OPEN = 1


class SerialHandler(GObject.Object):
    """
    Wrapper around a serial device. Handles *one* serial console
    and its settings, as well as its I/O.
    """

    reconnect_automatically = GObject.Property(type=bool, default=False)

    def __init__(self):
        super().__init__()
        self.serial = serial.Serial()
        self._serial_loop_running = False
        self._stop_serial_loop = False
        self._is_reconnecting = False

    @GObject.Property(type=int)
    def state(self):
        if self._is_reconnecting:
            return SerialHandlerState.RECONNECTING
        if self.serial.is_open:
            return SerialHandlerState.OPEN
        return SerialHandlerState.CLOSED

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
            case serial.FIVEBITS:
                return 5
            case serial.SIXBITS:
                return 6
            case serial.SEVENBITS:
                return 7
            case serial.EIGHTBITS:
                return 8

    @data_bits.setter
    def data_bits(self, value):
        match value:
            case 5:
                self.serial.bytesize = serial.FIVEBITS
            case 6:
                self.serial.bytesize = serial.SIXBITS
            case 7:
                self.serial.bytesize = serial.SEVENBITS
            case 8:
                self.serial.bytesize = serial.EIGHTBITS
            case _:
                raise ValueError

    @GObject.Property(type=int)
    def parity(self):
        match self.serial.parity:
            case serial.PARITY_NONE:
                p = Parity.NONE  # noqa: E241
            case serial.PARITY_EVEN:
                p = Parity.EVEN  # noqa: E241
            case serial.PARITY_ODD:
                p = Parity.ODD  # noqa: E241
            case serial.PARITY_MARK:
                p = Parity.MARK  # noqa: E241
            case serial.PARITY_SPACE:
                p = Parity.SPACE  # noqa: E241

        return p

    @parity.setter
    def parity(self, value):
        match int(value):
            case Parity.NONE:
                p = serial.PARITY_NONE  # noqa: E241
            case Parity.EVEN:
                p = serial.PARITY_EVEN  # noqa: E241
            case Parity.ODD:
                p = serial.PARITY_ODD  # noqa: E241
            case Parity.MARK:
                p = serial.PARITY_MARK  # noqa: E241
            case Parity.SPACE:
                p = serial.PARITY_SPACE  # noqa: E241

        self.serial.parity = p

    @GObject.Property(type=int)
    def stop_bits(self):
        bits = self.serial.stopbits
        match bits:
            case serial.STOPBITS_ONE:
                return 1
            case serial.STOPBITS_TWO:
                return 2

    @stop_bits.setter
    def stop_bits(self, value):
        match value:
            case 1:
                self.serial.stopbits = serial.STOPBITS_ONE
            case 2:
                self.serial.stopbits = serial.STOPBITS_TWO
            case _:
                raise ValueError

    @GObject.Property(type=int)
    def flow_control(self):
        if self.serial.xonxoff:
            return FlowControl.SOFTWARE
        elif self.serial.rtscts:
            return FlowControl.HARDWARE_RTS_CTS
        elif self.serial.dsrdtr:
            return FlowControl.HARDWARE_DSR_DTR
        return FlowControl.NONE

    @flow_control.setter
    def flow_control(self, value):
        self.serial.xonxoff = value == FlowControl.SOFTWARE
        self.serial.rtscts = value == FlowControl.HARDWARE_RTS_CTS
        self.serial.dsrdtr = value == FlowControl.HARDWARE_DSR_DTR

    def open(self):
        """Opens the serial port."""
        try:
            self.serial.open()
        except serial.serialutil.SerialException as e:
            if e.errno == 2:  # Happens with symlinked ports sometimes
                return
            traceback.print_exc()
            return
        self.serial_loop_start()
        self.notify("state")

    def close(self):
        """Closes the serial port."""
        self.serial.close()
        self.serial_loop_stop()
        self.notify("state")

    def write_text(self, text: str):
        """
        Writes UTF-8 text (as returned by VteTerminal::commit) to the
        serial device.
        """
        if self.props.state != SerialHandlerState.OPEN:
            return
        self.serial.write(text.encode("utf-8"))

    # Read loop handlers.
    # pyserial has no async handler, so reads must be done sequentially
    # every few seconds.

    @GObject.Signal(arg_types=(GLib.Bytes,))
    def read_done(self, data: GLib.Bytes):
        """Notifies consumer about a read on the serial device."""
        pass

    def serial_loop(self):
        self._serial_loop_running = True
        data = None
        while not self._stop_serial_loop:
            while not self._stop_serial_loop:
                try:
                    data = self.serial.read()
                except TypeError:  # Serial was closed
                    break
                except serial.serialutil.SerialException as e:
                    err = e.errno
                    if err == 9:  # Serial was closed mid-read
                        break
                    elif err == 16:  # Resource busy
                        break
                    # Connection has been lost
                    break

                if data:
                    GLib.idle_add(self.emit, "read_done", GLib.Bytes.new_take(data))

            if self.props.reconnect_automatically:
                if self.serial.is_open:
                    self.serial.close()
                reconnect_result = self._wait_for_reconnect()
                if reconnect_result is not True:
                    break
            else:
                break

        if self.serial.is_open:
            self.serial.close()

        GLib.idle_add(self.notify, "state")
        self._serial_loop_running = False

    def _wait_for_reconnect(self) -> bool:
        """
        Meant to be used within serial_loop to await a reconnect.

        Returns True if the reconnect succeeded, False if it was stopped
        (either by "close" button or by the reconnect option being switched
        off).
        """
        self._is_reconnecting = True
        GLib.idle_add(self.notify, "state")

        while self.props.reconnect_automatically and not self._stop_serial_loop:
            for port in serial.tools.list_ports.comports():
                if self.port == port[0]:
                    try:
                        self.serial.open()
                    except serial.serialutil.SerialException as e:
                        if e.errno == 2:  # Happens with symlinked ports sometimes
                            continue
                        traceback.print_exc()
                        self._is_reconnecting = False
                        # state notify is done in serial_loop
                        return False
                    self._is_reconnecting = False
                    GLib.idle_add(self.notify, "state")
                    return True

            time.sleep(1)

        self._is_reconnecting = False
        # state notify is done in serial_loop
        return False

    def serial_loop_start(self):
        if self._serial_loop_running:
            return False

        self._loop_read_queue = []
        self._serial_loop_thread = threading.Thread(
            target=self.serial_loop, daemon=True
        )
        self._serial_loop_thread.start()

    def serial_loop_stop(self):
        self._stop_serial_loop = True
        while self._serial_loop_running:
            time.sleep(0.1)
        self._stop_serial_loop = False
        self._serial_loop_thread = None
