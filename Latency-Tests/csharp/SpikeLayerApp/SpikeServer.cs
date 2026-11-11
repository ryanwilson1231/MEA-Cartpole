// TCP server on localhost:5005. Python (spike_client.py) is the client.
// All integers little-endian.
//
//   Python -> C#   SESS   <4sI  b"SESS", name length, then the name as UTF-8
//                         Opens sessions/<name>.bin and sessions/<name>.json.
//   Python -> C#   WAVE   <4sIII b"WAVE", window, left piece count, right piece count
//                         then that many <iI pairs (amplitude uV, length us), left first.
//                         0 pieces = that half stays silent.
//   C# -> Python   SPKS   <4sIQI60i (260 bytes) b"SPKS", window, first sample of the
//                         window in the .bin file, 60, then 60 spike counts.
//
// A window starts when the wave is played and lasts as long as the longer half.
// A bad wave (over 300 mV, or a length that isn't a multiple of 20 us) is not
// played: the server prints why and closes the connection.
//
// Nothing here touches McsUsbNet.dll; the hardware comes in through
// IStimulator and the `currentFrame` function.

using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;

class SpikeServer
{
    public const int PORT = 5005;
    const int  MAX_NAME_BYTES = 400;
    const long MAX_WINDOW_SECONDS_SLACK = 1;   // keep this much of the in-memory buffer spare

    readonly Recording rec;
    readonly IStimulator stim;
    readonly Func<long> currentFrame;          // best estimate of the frame being recorded right now
    readonly string sessionDir;
    TcpListener listener;
    volatile bool stopping;

    public SpikeServer(Recording rec, IStimulator stim, Func<long> currentFrame, string sessionDir)
    {
        this.rec = rec; this.stim = stim; this.currentFrame = currentFrame; this.sessionDir = sessionDir;
    }

    public void Stop()
    {
        stopping = true;
        try { listener.Stop(); } catch { }
    }

    public void Run()
    {
        listener = new TcpListener(IPAddress.Loopback, PORT);
        listener.Start();
        Console.WriteLine("  Listening on 127.0.0.1:{0}. Ctrl+C to stop.", PORT);
        while (!stopping)
        {
            TcpClient client;
            try { client = listener.AcceptTcpClient(); }
            catch (SocketException) { if (stopping) break; throw; }
            catch (ObjectDisposedException) { break; }
            Console.WriteLine("  Python connected.");
            Handle(client);
            Console.WriteLine("  Python disconnected.");
        }
    }

    // ------------------------------------------------------------ one client

    void Handle(TcpClient client)
    {
        client.NoDelay = true;
        var stream = client.GetStream();
        var r = new BinaryReader(stream);       // BinaryReader/Writer are always little-endian
        var w = new BinaryWriter(stream);
        try
        {
            while (!stopping)
            {
                byte[] magicBytes = ReadExactOrEof(r, 4);
                if (magicBytes == null) break;  // Python closed the connection
                string magic = Encoding.ASCII.GetString(magicBytes);

                if (magic == "SESS")
                {
                    uint len = r.ReadUInt32();
                    if (len == 0 || len > MAX_NAME_BYTES) { Refuse("SESS name length " + len + " is out of range"); return; }
                    string name = Encoding.UTF8.GetString(ReadExact(r, (int)len));
                    string why = rec.StartSession(name, sessionDir);
                    if (why != null) { Refuse(why); return; }
                    Console.WriteLine("  Session '{0}' started.", name);
                }
                else if (magic == "WAVE")
                {
                    uint window = r.ReadUInt32();
                    uint nLeft  = r.ReadUInt32();
                    uint nRight = r.ReadUInt32();
                    if (nLeft > WaveRules.MAX_PIECES || nRight > WaveRules.MAX_PIECES)
                    { Refuse(string.Format("window {0}: {1}/{2} pieces is more than the {3} allowed", window, nLeft, nRight, WaveRules.MAX_PIECES)); return; }
                    Piece[] left = ReadPieces(r, nLeft), right = ReadPieces(r, nRight);

                    string why = WaveRules.Validate(left, "left") ?? WaveRules.Validate(right, "right");
                    if (why == null && !rec.SessionOpen) why = "WAVE arrived before SESS; start a session first";
                    long durUs = Math.Max(WaveRules.DurationUs(left), WaveRules.DurationUs(right));
                    long maxUs = (rec.Capacity / rec.SampleRate - MAX_WINDOW_SECONDS_SLACK) * 1000000L;
                    if (why == null && durUs > maxUs)
                        why = string.Format("wave lasts {0} us; the server holds at most {1} us", durUs, maxUs);
                    if (why != null) { Refuse("window " + window + ": " + why + ". Not played."); return; }

                    long firstSample; int[] counts;
                    if (!RunWindow(window, left, right, durUs, out firstSample, out counts)) return;
                    SendSpikes(w, window, firstSample, counts);
                }
                else
                {
                    Refuse("unknown message type '" + magic + "'");
                    return;
                }
            }
        }
        catch (EndOfStreamException) { Console.WriteLine("  Python closed the connection mid-message."); }
        catch (IOException ex) { Console.WriteLine("  Connection error: " + ex.Message); }
        finally
        {
            rec.EndSession();
            client.Close();
        }
    }

    bool RunWindow(uint window, Piece[] left, Piece[] right, long durUs, out long firstSample, out int[] counts)
    {
        int n = (int)WaveRules.UsToSamples(durUs, rec.SampleRate);
        counts = new int[Recording.CHANNELS];

        if (n == 0)                             // nothing to play, nothing to record
        {
            firstSample = rec.SessionSample(currentFrame());
            rec.LogWindow(window, firstSample, 0, left, right, counts);
            return true;
        }

        stim.Play(left, right, durUs);
        long start = currentFrame();            // see README: estimate, not yet hardware-timed
        firstSample = rec.SessionSample(start);

        int margin = rec.SampleRate * SpikeCounter.MARGIN_MS / 1000;
        int timeoutMs = (int)(durUs / 1000) + 2000;
        if (!rec.WaitFor(start + n + margin, timeoutMs))
        {
            Refuse("window " + window + ": no data from the MEA for 2 s past the window. Check the USB connection.");
            return false;
        }

        var mask = WaveRules.SpikeMask(left, right, n, rec.SampleRate, SpikeCounter.MASK_AFTER_US);
        counts = SpikeCounter.CountWindow(rec, start, n, mask);
        if (counts == null)
        {
            Refuse("window " + window + ": samples were no longer in memory when counting");
            return false;
        }
        rec.LogWindow(window, firstSample, n, left, right, counts);
        return true;
    }

    static void SendSpikes(BinaryWriter w, uint window, long firstSample, int[] counts)
    {
        w.Write(Encoding.ASCII.GetBytes("SPKS"));
        w.Write(window);
        w.Write((ulong)firstSample);
        w.Write((uint)counts.Length);
        foreach (int c in counts) w.Write(c);
        w.Flush();
    }

    static void Refuse(string why)
    {
        Console.WriteLine("  REFUSED: " + why);
        Console.WriteLine("  Closing the connection.");
    }

    static Piece[] ReadPieces(BinaryReader r, uint count)
    {
        var p = new Piece[count];
        for (int i = 0; i < count; i++) p[i] = new Piece(r.ReadInt32(), r.ReadUInt32());
        return p;
    }

    static byte[] ReadExact(BinaryReader r, int n)
    {
        var b = r.ReadBytes(n);
        if (b.Length != n) throw new EndOfStreamException();
        return b;
    }

    // null if the stream ended cleanly before the first byte
    static byte[] ReadExactOrEof(BinaryReader r, int n)
    {
        var b = r.ReadBytes(n);
        if (b.Length == 0) return null;
        if (b.Length != n) throw new EndOfStreamException();
        return b;
    }
}
