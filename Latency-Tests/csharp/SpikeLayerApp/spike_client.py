"""
Client for the C# spike server (SpikeLayerApp.exe --serve) on localhost:5005.

    import spike_client
    spike_client.start_session("2026-11-10_saline_01")
    first_sample, counts = spike_client.play_and_read(1, left_wave, right_wave)

A wave is a list of (amplitude_uV, length_us) pieces, e.g. a 100 ms window with
one biphasic pulse at the start:
    [(75_000, 200), (-75_000, 200), (0, 99_600)]
An empty list means that half stays silent. Lengths must be multiples of 20 us
and amplitudes at most 300 mV (300_000 uV), or the server refuses the wave,
prints why, and closes the connection (you'll get a ConnectionError here).

play_and_read blocks until the window is over and the spikes are counted:
about the wave's length plus a few tens of ms.
"""
import socket
import struct

HOST = "127.0.0.1"
PORT = 5005
N_CHANNELS = 60

_SPKS = struct.Struct("<4sIQI60i")   # 260 bytes
_sock = None


def _connect():
    global _sock
    if _sock is None:
        _sock = socket.create_connection((HOST, PORT))
        _sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return _sock


def _recv_exact(n):
    data = b""
    while len(data) < n:
        chunk = _sock.recv(n - len(data))
        if not chunk:
            close()
            raise ConnectionError("The C# server closed the connection. Its console says why.")
        data += chunk
    return data


def start_session(name):
    """Start a session. The server saves the raw recording as sessions/<name>.bin and .json."""
    encoded = name.encode("utf-8")
    _connect().sendall(struct.pack("<4sI", b"SESS", len(encoded)) + encoded)


def play_and_read(window, left_wave, right_wave):
    """
    Play left_wave on electrodes 0-29 and right_wave on 30-59, record for the
    length of the longer one, and return (first_sample, counts):
      first_sample: index of the window's first sample in sessions/<name>.bin
      counts: list of 60 spike counts, one per electrode
    """
    msg = [struct.pack("<4sIII", b"WAVE", window, len(left_wave), len(right_wave))]
    for amplitude_uv, length_us in list(left_wave) + list(right_wave):
        msg.append(struct.pack("<iI", int(amplitude_uv), int(length_us)))
    _connect().sendall(b"".join(msg))

    magic, got_window, first_sample, n, *counts = _SPKS.unpack(_recv_exact(_SPKS.size))
    if magic != b"SPKS" or got_window != window or n != N_CHANNELS:
        close()
        raise ConnectionError(f"Unexpected reply: {magic!r}, window {got_window} (sent {window}), {n} channels")
    return first_sample, counts


def close():
    """Close the connection. The server ends the session and finishes the .json."""
    global _sock
    if _sock is not None:
        try:
            _sock.close()
        finally:
            _sock = None
