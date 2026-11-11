// Plays waves on the MEA's two stimulus generators.
//   left  half -> generator 1 (STG 1) -> electrodes 0-29
//   right half -> generator 2 (STG 2) -> electrodes 30-59
// An electrode is connected to its generator whenever the amplitude isn't 0.
//
// Ported from _setup_stimulation and _send in Baseline-Protocol/Hardware/mea_device.py.
// Uses CStg200xDownloadNet (not CStimulusFunctionNet, which has no electrode setup).

using System;
using Mcs.Usb;

class Stimulator : IStimulator, IDisposable
{
    const uint HEADSTAGE = 0;                     // SCU port the headstage is on (HS1 = 0)
    const int  N_ELECTRODES = 60;
    const int  LEFT_COUNT = 30;                   // electrodes 0-29 on generator 1, 30-59 on generator 2

    // CreateSideband timing, same values as mea_device.py
    const uint SIDEBAND_BIT0 = 40, SIDEBAND_BIT3 = 800, SIDEBAND_BIT4 = 40;

    readonly CStg200xDownloadNet stg = new CStg200xDownloadNet();

    public Stimulator(CMcsUsbListEntryNet entry)
    {
        uint status = stg.Connect(entry);
        if (status != 0) throw new InvalidOperationException("stimulator Connect failed: status " + status);
        Setup();
    }

    void Setup()
    {
        for (uint e = 0; e < N_ELECTRODES; e++)
        {
            var generator = e < LEFT_COUNT ? ElectrodeDacMuxEnumNet.Stg1 : ElectrodeDacMuxEnumNet.Stg2;
            stg.SetElectrodeMode(HEADSTAGE, e, ElectrodeModeEnumNet.emAutomatic);
            stg.SetElectrodeEnable(HEADSTAGE, e, 0, true);
            stg.SetElectrodeDacMux(HEADSTAGE, e, 0, generator);
            stg.SetEnableAmplifierProtectionSwitch(HEADSTAGE, e, false);
            stg.SetBlankingEnable(HEADSTAGE, e, true);      // hide stim artifacts in the recording
        }
        stg.SetVoltageMode(0);
        stg.SetupTrigger(0, new uint[] { 255 }, new uint[] { 255 }, new uint[] { 1 });
    }

    public void Play(Piece[] left, Piece[] right, long windowUs)
    {
        // Both halves are always uploaded, so a silent half can't replay an old wave.
        Upload(2 * HEADSTAGE + 0, left, windowUs);
        Upload(2 * HEADSTAGE + 1, right, windowUs);
        stg.SendStart(1);
    }

    void Upload(uint channel, Piece[] wave, long windowUs)
    {
        long used = WaveRules.DurationUs(wave);
        int n = wave.Length + (used < windowUs ? 1 : 0);   // pad with silence to the window length
        var amps = new int[n];
        var durs = new ulong[n];
        var active = new int[n];
        for (int i = 0; i < wave.Length; i++)
        {
            amps[i] = wave[i].AmplitudeUv;
            durs[i] = wave[i].LengthUs;
            active[i] = wave[i].AmplitudeUv != 0 ? 1 : 0;
        }
        if (used < windowUs) durs[n - 1] = (ulong)(windowUs - used);

        // The sideband tells the headstage when to connect the electrodes to the generator.
        var sideband = stg.Stimulus.CreateSideband(active, new int[n], durs,
                                                   SIDEBAND_BIT0, SIDEBAND_BIT3, SIDEBAND_BIT4);
        stg.PrepareAndSendData(channel, amps, durs, STG_DestinationEnumNet.channeldata_voltage);
        stg.PrepareAndSendData(channel, sideband.Sideband, sideband.Duration, STG_DestinationEnumNet.syncoutdata);
    }

    public void Dispose()
    {
        try { stg.Disconnect(); } catch { }
    }
}
