"""
MEA2100-Mini-60 hardware interface (pythonnet path).

FIXED VERSION - see Hardware-Pythonnet-Path/FIXES.md for the full list.
The biggest change: the stimulation code was written against classes that do not
exist in McsUsbNet.dll. It now uses CStimulusFunctionNet, which is the real API.
"""
import os
import subprocess
import sys
import time
from threading import Event

import numpy as np

# --- DLL loading -----------------------------------------------------------
# FIX: the DLL carries a mark-of-the-web and lives under OneDrive, so .NET
# refuses to load it ("assembly from a network location"). Unblock it first.
_DLL_DIR = os.path.dirname(os.path.abspath(__file__))
_DLL_PATH = os.path.join(_DLL_DIR, "McsUsbNet.dll")

if os.path.exists(_DLL_PATH):
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Unblock-File -Path '{_DLL_PATH}'"],
            check=False, capture_output=True, timeout=30,
        )
    except Exception:
        pass   # not fatal; AddReference will report the real problem

sys.path.append(_DLL_DIR)

import clr  # noqa: E402
clr.AddReference("McsUsbNet")

from System import Array, Int32, UInt64, IntPtr, Int64  # noqa: E402
from System.Runtime.InteropServices import Marshal  # noqa: E402

# FIX: CMcsUsbBStimNet does not exist in McsUsbNet.dll. The real stimulation
# class is CStimulusFunctionNet, built directly from the device.
from Mcs.Usb import (  # noqa: E402
    CMcsUsbListNet,
    DeviceEnumNet,
    CMeaUSBDeviceNet,
    DataModeEnumNet,
    DigitalDatastreamEnableEnumNet,
    SampleSizeNet,
    SampleDstSizeNet,
    CSCUFunctionNet,
    CStimulusFunctionNet,
    STG_DestinationEnumNet,
)


class IntegratedMEAInterface:
    def __init__(self, stim_gain=1.0):
        self.dacq = None
        self.stim = None
        self.device_connected = False
        self.channels_in_block = 0
        self.num_channels = 60
        self.buffer_size = 2500        # 2500 samples / 50 kHz = 50 ms of history
        self.samplerate = 50000        # 50 kHz
        self.data_buffer = np.zeros((self.num_channels, self.buffer_size))
        self.data_ready = Event()
        self.last_action = 0
        self.failure_count = 0

        # Filled in once the stimulator reports its ranges.
        self.volt_res_uv = None        # microvolts per DAC step
        self.volt_range_uv = None      # +/- range in microvolts
        self.stim_gain = stim_gain     # scales the generated waveform before sending

    # ------------------------------------------------------------- connect

    def connect_to_device(self):
        device_list = CMcsUsbListNet(DeviceEnumNet.MCS_DEVICE_USB)
        usb_entries = device_list.GetUsbListEntries()
        if len(usb_entries) <= 0:
            print("No MEA devices found!")
            return False
        print(f"Found {len(usb_entries)} MEA devices")

        self.dacq = CMeaUSBDeviceNet()
        self.dacq.ChannelDataEvent += self.handle_data_event
        self.dacq.ErrorEvent += lambda msg, action: print(f"Error: {msg}")

        status = self.dacq.Connect(usb_entries[0])
        if status != 0:
            print(f"Connection to MEA device failed: {status}")
            return False

        self.configure_data_acquisition()
        self.configure_stimulation()
        self.device_connected = True
        return True

    def configure_data_acquisition(self):
        self.dacq.StopDacq(0)

        scu = CSCUFunctionNet(self.dacq)
        scu.SetDacqLegacyMode(False)

        self.dacq.SetSamplerate(self.samplerate, 0, 0)
        self.dacq.SetDataMode(DataModeEnumNet.Signed_32bit, 0)
        self.dacq.SetNumberOfAnalogChannels(60, 0, 0, 8, 0)
        self.dacq.EnableDigitalIn(
            DigitalDatastreamEnableEnumNet.DigitalIn
            | DigitalDatastreamEnableEnumNet.DigitalOut
            | DigitalDatastreamEnableEnumNet.Hs1SidebandLow
            | DigitalDatastreamEnableEnumNet.Hs1SidebandHigh, 0)
        self.dacq.EnableChecksum(True, 0)

        a, d, c, t, cib = (Int32(0),) * 5
        a, d, c, t, cib = self.dacq.GetChannelLayout(a, d, c, t, cib, 0)
        self.channels_in_block = int(cib)
        print(f"Channel layout: {int(a)} analog, {int(d)} digital, "
              f"{self.channels_in_block} in block")

        queue_size = self.samplerate            # 1 s ring buffer per channel
        threshold = self.samplerate // 10       # callback every 100 ms

        self.dacq.ChannelBlock.SetSelectedChannels(
            self.channels_in_block // 2, queue_size, threshold,
            SampleSizeNet.SampleSize32Signed,
            SampleDstSizeNet.SampleDstSize32,
            self.channels_in_block)
        self.dacq.ChannelBlock.SetCommonThreshold(threshold)
        self.dacq.ChannelBlock.SetCheckChecksum(int(c), int(t))

    def configure_stimulation(self):
        """FIX: rewritten against CStimulusFunctionNet (the real API)."""
        try:
            self.stim = CStimulusFunctionNet(self.dacq)
        except Exception as exc:
            print(f"Failed to create stimulator: {exc}")
            return False

        # FIX: this settles the old `np.clip(waveform, -500, 500)` question -
        # amplitudes are DAC steps, and the device tells us what a step is worth.
        try:
            self.volt_range_uv = self.stim.GetVoltageRangeInMicroVolt(0)
            self.volt_res_uv = self.stim.GetVoltageResolutionInMicroVolt(0)
            print(f"Stimulator: +/-{self.volt_range_uv} uV range, "
                  f"{self.volt_res_uv} uV per step")
        except Exception as exc:
            print(f"Could not query stimulator ranges: {exc}")
            return False

        print("Stimulation interface configured successfully")
        return True

    # ------------------------------------------------------------ recording

    def start_recording(self):
        if not self.device_connected:
            print("Device not connected. Cannot start recording.")
            return False
        self.dacq.StartDacq()
        print("Recording started")
        return True

    def stop_recording(self):
        if self.device_connected:
            self.dacq.StopDacq(0)
            print("Recording stopped")

    def disconnect(self):
        self.stop_recording()
        if self.dacq:
            self.dacq.Disconnect()
        self.device_connected = False
        print("Disconnected from MEA device")

    def handle_data_event(self, dacq, cb_handle, num_frames):
        """Drain the DLL ring buffer into data_buffer.

        FIX: the old version did np.array(list(net_array)) per channel, which
        marshals element by element - about 60 ms for 60 channels against a
        100 ms callback budget. Marshal.Copy does the same work in one bulk
        memcpy, measured at ~7.6 ms for 60 channels.
        """
        try:
            n = min(self.channels_in_block // 2, self.num_channels)
            for i in range(n):
                frames_ret = Int32(0)
                data = dacq.ChannelBlock.ReadFramesI32(i, 0, num_frames, frames_ret)
                count = int(frames_ret)
                if count <= 0:
                    continue
                arr = self._to_numpy(data[0])
                if len(arr) >= self.buffer_size:
                    self.data_buffer[i] = arr[-self.buffer_size:]
                else:
                    self.data_buffer[i] = np.pad(arr, (0, self.buffer_size - len(arr)))
            self.data_ready.set()
        except Exception as exc:
            print(f"Error processing MEA data: {exc}")

    @staticmethod
    def _to_numpy(net_int_array):
        """Bulk-copy a .NET int[] into a numpy array (one interop call)."""
        n = net_int_array.Length
        out = np.empty(n, dtype=np.int32)
        Marshal.Copy(net_int_array, 0, IntPtr.op_Explicit(Int64(out.ctypes.data)), n)
        return out

    def read_neural_data_buffer(self):
        return self.data_buffer.copy()

    # --------------------------------------------------------- stimulation

    def send_stimulation(self, waveform_uv, selected_channels, sample_us=200):
        """Send a waveform as amplitude/duration steps.

        FIX: PrepareAndSendData takes (amplitude[], duration[]) step pairs, not
        a raw sampled waveform. Each sample becomes one step of `sample_us`.
        generate_stim_wave() returns 500 samples spanning 100 ms, so the default
        200 us per step reproduces that timing.
        """
        if not self.device_connected or self.stim is None:
            print("Device not connected or stimulation not available")
            return False
        if self.volt_res_uv is None:
            print("Stimulator ranges unknown - refusing to stimulate")
            return False

        try:
            max_steps = int(self.volt_range_uv // self.volt_res_uv)
            steps = np.round(np.asarray(waveform_uv, dtype=float)
                             * self.stim_gain / self.volt_res_uv)
            steps = np.clip(steps, -max_steps, max_steps).astype(np.int32)

            amps = Array[Int32]([int(v) for v in steps])
            durs = Array[UInt64]([UInt64(int(sample_us))] * len(steps))

            for ch in selected_channels:
                self.stim.PrepareAndSendData(
                    int(ch), amps, durs, STG_DestinationEnumNet.channeldata_voltage)
                self.stim.SetupTriggerSingle(0, 1 << int(ch), 0, 1)

            self.stim.SendStart(1)
            return True
        except Exception as exc:
            print(f"Error sending stimulation: {exc}")
            return False

    def stimulate_neurons(self, pole_angle, pole_angular_velocity, reward):
        from square import generate_stim_wave

        # FIX: threshold was 0.262 rad, but CartPole-v1 terminates at 0.2095 rad,
        # so the punishment branch could never fire. 0.15 rad fires before failure.
        if np.abs(pole_angle) < 0.15:
            stim_wave = generate_stim_wave(pole_angle, pole_angular_velocity, 100)
        else:
            stim_wave = self.generate_random_noise(100)
            self.failure_count += 1

        # Stimulation encodes the observation (which way the pole leans),
        # not the action just taken.
        if pole_angle < 0:
            selected_channels = range(self.num_channels // 2)
        else:
            selected_channels = range(self.num_channels // 2, self.num_channels)

        self.send_stimulation(stim_wave, selected_channels)

    def generate_random_noise(self, duration, sampling_rate=500, base_voltage_amp=150):
        num_samples = int(sampling_rate * (duration / 1000.0))
        t = np.linspace(0, duration / 1000.0, num_samples)

        voltage_amp = base_voltage_amp * min(2, 1 + 0.1 * self.failure_count)
        base_freq = 5
        max_freq = min(50, base_freq + 3 * self.failure_count)
        f1 = np.random.uniform(base_freq, max_freq)
        f2 = np.random.uniform(base_freq * 2, max_freq * 2)

        noise = (voltage_amp * np.sin(2 * np.pi * f1 * t + np.random.uniform(0, 2 * np.pi))
                 + 0.5 * voltage_amp * np.sin(2 * np.pi * f2 * t + np.random.uniform(0, 2 * np.pi)))
        noise += np.random.uniform(-voltage_amp, voltage_amp, num_samples)
        return noise

    # ------------------------------------------------------------- readout

    def extract_neuron_action(self, raw_neural_data, threshold=3):
        from spike import MADs, count_spikes

        # FIX: the old version passed np.linspace(0, 1, N), telling MADs() the
        # data spanned 1 second when it actually spans N/samplerate = 50 ms.
        # Every filter cutoff was therefore off by about 20x.
        n = raw_neural_data.shape[1]
        time_array = np.linspace(0, n / self.samplerate, n)

        median_abs_deviations, abs_activity, _, _ = MADs(time_array, raw_neural_data)
        spike_count = count_spikes(abs_activity, median_abs_deviations, threshold)

        num_channels = len(spike_count)
        left = np.sum(spike_count[:num_channels // 2])
        right = np.sum(spike_count[num_channels // 2:])

        # FIX: the old version was `0 if left > right else 1`, so every tie went
        # right. That biased the agent toward one direction whenever the readout
        # was ambiguous, which at low spike counts is most of the time.
        if left > right:
            action = 0
        elif right > left:
            action = 1
        else:
            action = int(np.random.randint(2))

        self.last_action = action
        return action
