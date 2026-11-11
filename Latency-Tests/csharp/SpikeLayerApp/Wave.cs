// Waves sent by Python, the rules they must pass, and the interface the
// server uses to play them. Nothing here touches McsUsbNet.dll, so this file
// can be compiled and tested on a machine without the hardware.

using System;
using System.Collections.Generic;

// One piece of a wave: hold `AmplitudeUv` for `LengthUs`.
struct Piece
{
    public int  AmplitudeUv;
    public uint LengthUs;
    public Piece(int amplitudeUv, uint lengthUs) { AmplitudeUv = amplitudeUv; LengthUs = lengthUs; }
}

interface IStimulator
{
    // Upload both halves and start them together. `windowUs` is the length of
    // the longer half; the shorter (or empty) half is padded with silence.
    void Play(Piece[] left, Piece[] right, long windowUs);
}

static class WaveRules
{
    public const int  MAX_AMPLITUDE_UV = 300000;   // 300 mV
    public const int  STEP_US          = 20;       // stimulator resolution = 1 sample at 50 kHz
    public const int  MAX_PIECES       = 100000;   // per half; guards against a garbage header

    // Returns null if the wave is safe to play, otherwise the reason it isn't.
    public static string Validate(Piece[] wave, string side)
    {
        for (int i = 0; i < wave.Length; i++)
        {
            long a = wave[i].AmplitudeUv;
            if (Math.Abs(a) > MAX_AMPLITUDE_UV)
                return string.Format("{0} piece {1}: amplitude {2} uV is over the {3} uV (300 mV) limit",
                                     side, i, a, MAX_AMPLITUDE_UV);
            if (wave[i].LengthUs == 0)
                return string.Format("{0} piece {1}: length is 0 us", side, i);
            if (wave[i].LengthUs % STEP_US != 0)
                return string.Format("{0} piece {1}: length {2} us is not a multiple of {3} us",
                                     side, i, wave[i].LengthUs, STEP_US);
        }
        return null;
    }

    public static long DurationUs(Piece[] wave)
    {
        long t = 0;
        foreach (var p in wave) t += p.LengthUs;
        return t;
    }

    // Samples to ignore when counting spikes: from the start of every non-zero
    // piece until `maskAfterUs` after it ends, on either half. Applied to all
    // electrodes, because the artifact spreads across the dish.
    public static bool[] SpikeMask(Piece[] left, Piece[] right, int nSamples, int sampleRate, int maskAfterUs)
    {
        var mask = new bool[nSamples];
        foreach (var wave in new[] { left, right })
        {
            long t = 0;
            foreach (var p in wave)
            {
                if (p.AmplitudeUv != 0)
                {
                    long from = UsToSamples(t, sampleRate);
                    long to   = UsToSamples(t + p.LengthUs + maskAfterUs, sampleRate);
                    for (long k = Math.Max(0, from); k < Math.Min(nSamples, to); k++) mask[k] = true;
                }
                t += p.LengthUs;
            }
        }
        return mask;
    }

    public static long UsToSamples(long us, int sampleRate) { return us * sampleRate / 1000000; }
}
