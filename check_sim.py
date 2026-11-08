"""Does stimulating the left vs right input electrodes change what the output electrodes do?
Runs the culture with no feedback, stimulates one input electrode at 25 Hz for 10 windows,
and compares output electrode activity. Prints normalized left vs right output rates."""
import numpy as np, common as c
from common import CH, MOTOR_LEFT, MOTOR_RIGHT
rng = np.random.default_rng(0)
cu = c.Culture(0)
base = cu.baseline
def trial(label, n_windows=10):
    tot = np.zeros(60)
    enc_t = 0.0
    for _ in range(n_windows):
        pulses=[]; t=enc_t
        while t < c.WINDOW_MS:
            pulses.append(((CH[label],), t, c.ENCODE_CURRENT)); t += 40.0
        enc_t = t - c.WINDOW_MS
        tot += cu.run(c.WINDOW_MS, pulses=pulses)
    n = tot / n_windows / base
    return n[MOTOR_LEFT].mean(), n[MOTOR_RIGHT].mean(), tot[MOTOR_LEFT].sum(), tot[MOTOR_RIGHT].sum()
for name, labels in (("LEFT input", (28,38,48)), ("RIGHT input", (58,68,78))):
    for lab in labels:
        res=[trial(lab) for _ in range(3)]
        L=np.mean([r[0] for r in res]); R=np.mean([r[1] for r in res])
        print(f"{name} electrode {lab}: normalized output left {L:.2f}  right {R:.2f}  (left minus right {L-R:+.2f})", flush=True)
rest=[]
for _ in range(3):
    t=np.zeros(60)
    for _ in range(10): t+=cu.run(c.WINDOW_MS)
    n=t/10/base; rest.append((n[MOTOR_LEFT].mean(), n[MOTOR_RIGHT].mean()))
print("NO stimulation:        normalized output left %.2f  right %.2f" % tuple(np.mean(rest,0)))
