"""Round 3: V_batt over the first 5 s of each Pi bag (/vehicle_state index 1, 50 Hz), the State-1 window in which
the section 9.7a configuration check (FC-window entry conditions, V_batt < 8.0 V) must run before any regen window."""
import glob, os, sys
from mcap_ros2.reader import read_ros2_messages
n_hi = 0; n = 0
for d in sorted(glob.glob(sys.argv[1] + '/rosbag_*')):
    f = glob.glob(d + '/*.mcap')
    if not f: continue
    t0 = None; vb = []
    for m in read_ros2_messages(f[0], topics=['/vehicle_state']):
        x = list(m.ros_msg.data)
        if len(x) < 10: continue
        t = m.log_time_ns / 1e9; t0 = t0 or t
        if t - t0 > 5.0: break
        if x[1] > 1.0: vb.append(x[1])
    if not vb: continue
    n += 1; med = sorted(vb)[len(vb)//2]; n_hi += med >= 8.0
    print(f"{os.path.basename(d):45s} V_batt first 5 s median {med:.2f} V {'>= 8.0 V: no config check, no regen windows' if med >= 8.0 else ''}")
print(f"bags starting at or above 8.0 V: {n_hi} of {n}")
