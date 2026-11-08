"""
A more realistic simulated MEA for the reward signaling experiments.

Compared with the team's baseline (60 identical neurons, one per electrode, random wiring):
  * Real electrode geometry: the 60 electrodes sit at their chip positions (200 micrometre pitch).
  * Several neurons around each electrode, plus extra neurons nobody records (most of a real
    culture is not under an electrode).
  * 80 percent excitatory (regular spiking) and 20 percent inhibitory (fast spiking), with
    varied parameters, as in Izhikevich (2003).
  * Connection probability falls off with distance, and spikes arrive after a delay that
    grows with distance.
  * STDP on excitatory to excitatory synapses, plus slow homeostatic scaling of incoming
    excitation so firing rates stay near a target.
  * An electrode pulse is not a private line to one neuron. Its current spreads to nearby
    neurons and fades with distance. Each electrode records only the neurons close to it.

What it still does not have: real network bursting, calcium or glia effects, axon geometry.
Parameters are plausible, not fitted to a real dish.

The only way anything gets in is electrode current (set_current). There is no reward input.
"""
import numpy as np
from brian2 import (NeuronGroup, Synapses, PoissonInput, SpikeMonitor, Network,
                    NetworkOperation, defaultclock, prefs, ms, Hz)

prefs.codegen.target = "numpy"

PITCH_UM = 200.0
PER_ELECTRODE = 3        # neurons placed right around each electrode
N_HIDDEN = 120           # unrecorded neurons scattered over the whole area
JITTER_UM = 30.0         # spread of neurons around their electrode
RECORD_RADIUS_UM = 60.0  # an electrode hears neurons within this distance
STIM_SIGMA_UM = 50.0     # how far an electrode pulse reaches (gaussian width)
P0, LAMBDA_UM = 0.06, 600.0
FRAC_INHIB = 0.2
W_EE_MAX_INIT, W_MAX = 2.0, 5.0
W_EI, W_IE, W_II = 1.5, 2.5, 2.0     # mean-ish sizes of the fixed synapses
BG_RATE_HZ, BG_N, BG_W = 20.0, 100, 1.2
TARGET_HZ, SCALING_ETA = 3.0, 0.05


class RealisticMEA:
    def __init__(self, labels):
        defaultclock.dt = 0.1 * ms
        self.labels = list(labels)
        n_el = len(self.labels)
        ex = np.array([(l // 10 - 1) * PITCH_UM for l in self.labels], float)
        ey = np.array([(l % 10 - 1) * PITCH_UM for l in self.labels], float)
        self.electrode_xy = np.stack([ex, ey], 1)

        # --- neuron positions: clustered near electrodes, plus hidden ones everywhere
        own = np.repeat(np.arange(n_el), PER_ELECTRODE)
        pos_near = self.electrode_xy[own] + np.random.randn(len(own), 2) * JITTER_UM
        lo, hi = self.electrode_xy.min(0) - PITCH_UM / 2, self.electrode_xy.max(0) + PITCH_UM / 2
        pos_hidden = lo + np.random.rand(N_HIDDEN, 2) * (hi - lo)
        pos = np.vstack([pos_near, pos_hidden])
        N = len(pos)
        self.N = N
        self.pos = pos

        # --- which electrode records which neuron (nearest one within the record radius)
        d_el = np.linalg.norm(pos[:, None, :] - self.electrode_xy[None], axis=2)  # N x 60
        nearest = d_el.argmin(1)
        self.record_channel = np.where(d_el.min(1) <= RECORD_RADIUS_UM, nearest, -1)
        self.record_channel[:len(own)] = own     # a neuron placed at an electrode is heard by it

        # --- stimulation spread: current each neuron gets per unit electrode current
        self.stim_gain = np.exp(-d_el ** 2 / (2 * STIM_SIGMA_UM ** 2))    # N x 60
        self.stim_gain[self.stim_gain < 0.02] = 0.0

        # --- neuron types and heterogeneous Izhikevich parameters
        inhib = np.random.rand(N) < FRAC_INHIB
        r = np.random.rand(N)
        a = np.where(inhib, 0.02 + 0.08 * r, 0.02)
        b = np.where(inhib, 0.25 - 0.05 * r, 0.2)
        c = np.where(inhib, -65.0, -65.0 + 15 * r ** 2)
        d = np.where(inhib, 2.0, 8.0 - 6 * r ** 2)
        self.inhib = inhib

        self.neurons = NeuronGroup(
            N,
            """
            dv/dt = (0.04*v**2 + 5*v + 140 - u + I) / ms : 1
            du/dt = a * (b*v - u) / ms : 1
            I : 1
            a : 1 (constant)
            b : 1 (constant)
            c : 1 (constant)
            d : 1 (constant)
            """,
            threshold="v >= 30", reset="v = c; u += d", method="euler")
        self.neurons.a, self.neurons.b, self.neurons.c, self.neurons.d = a, b, c, d
        self.neurons.v = -65
        self.neurons.u = b * -65

        # --- connectivity: distance dependent, with delays
        D = np.linalg.norm(pos[:, None, :] - pos[None], axis=2)
        P = P0 * np.exp(-D / LAMBDA_UM)
        np.fill_diagonal(P, 0.0)
        pre, post = np.nonzero(np.random.rand(N, N) < P)
        delay_ms = 1.0 + D[pre, post] / 300.0       # about 0.3 m/s conduction plus 1 ms
        pre_inh = inhib[pre]
        post_inh = inhib[post]

        ee = (~pre_inh) & (~post_inh)
        ei = (~pre_inh) & post_inh
        ie = pre_inh & (~post_inh)
        ii = pre_inh & post_inh

        self.syn_ee = Synapses(
            self.neurons, self.neurons,
            model="""
            w : 1
            dApre/dt  = -Apre  / (20*ms) : 1 (event-driven)
            dApost/dt = -Apost / (20*ms) : 1 (event-driven)
            """,
            on_pre="""
            v_post += w
            Apre += 0.01 * W_MAX
            w = clip(w + Apost, 0, W_MAX)
            """,
            on_post="""
            Apost -= 0.0105 * W_MAX
            w = clip(w + Apre, 0, W_MAX)
            """,
            namespace={"W_MAX": W_MAX})
        self.syn_ee.connect(i=pre[ee], j=post[ee])
        self.syn_ee.w = np.random.rand(ee.sum()) * W_EE_MAX_INIT
        self.syn_ee.delay = delay_ms[ee] * ms
        self._ee_post = post[ee]

        def static(mask, sign, scale):
            s = Synapses(self.neurons, self.neurons, model="w : 1", on_pre="v_post += w")
            s.connect(i=pre[mask], j=post[mask])
            s.w = sign * np.random.rand(mask.sum()) * scale
            s.delay = delay_ms[mask] * ms
            return s
        self.syn_ei = static(ei, +1, W_EI)
        self.syn_ie = static(ie, -1, W_IE)
        self.syn_ii = static(ii, -1, W_II)

        background = PoissonInput(self.neurons, "v", N=BG_N, rate=BG_RATE_HZ * Hz, weight=BG_W)
        self.spikes = SpikeMonitor(self.neurons, record=False)

        # homeostasis: every second, nudge each neuron's incoming excitation toward a target rate
        self._last_counts = np.zeros(N)
        def scale_weights():
            counts = np.array(self.spikes.count)
            rate = (counts - self._last_counts) / 1.0       # spikes in the last second
            self._last_counts = counts
            factor = 1 + SCALING_ETA * (TARGET_HZ - rate) / TARGET_HZ
            factor = np.clip(factor, 0.9, 1.1)
            w = np.array(self.syn_ee.w)
            self.syn_ee.w = np.clip(w * factor[self._ee_post], 0, W_MAX)
        homeostasis = NetworkOperation(scale_weights, dt=1000 * ms)

        self.network = Network(self.neurons, self.syn_ee, self.syn_ei, self.syn_ie, self.syn_ii,
                               background, self.spikes, homeostasis)

    # ---- the interface the culture uses
    def set_current(self, electrode_current):
        """electrode_current: length 60 vector of current at each electrode."""
        self.neurons.I = self.stim_gain @ np.asarray(electrode_current, float)

    def channel_counts(self):
        """Cumulative spike count per electrode (length 60) from the neurons it can hear."""
        per_neuron = np.array(self.spikes.count)
        out = np.zeros(len(self.labels))
        m = self.record_channel >= 0
        np.add.at(out, self.record_channel[m], per_neuron[m])
        return out
