import glob,os,sys
from mcap_ros2.reader import read_ros2_messages
tot=[0,0,0,0]
for d in sorted(glob.glob(sys.argv[1]+'/rosbag_*')):
    f=glob.glob(d+'/*.mcap')
    if not f: continue
    ib=[];vb=[]
    for m in read_ros2_messages(f[0], topics=['/vehicle_state']):
        x=list(m.ros_msg.data)
        if len(x)<10: continue
        ib.append(x[2]); vb.append(x[1])
    def runs(th):
        return any(all(ib[k+j]>th for j in range(5)) for k in range(len(ib)-5))
    def runs_and_low(th):
        # a 100 ms BT run above th occurring at any time, and V_batt<8.0 at some later sample
        first=next((k for k in range(len(ib)-5) if all(ib[k+j]>th for j in range(5))),None)
        return first is not None and any(1<v<8.0 for v in vb[first:])
    r=(runs(1.0),runs(0.4),runs_and_low(1.0),runs_and_low(0.4))
    for i,x in enumerate(r): tot[i]+=x
    print(f"{os.path.basename(d):45s} pass@1.0A {r[0]!s:5} pass@0.4A {r[1]!s:5} pass@1.0A then Vb<8 {r[2]!s:5} pass@0.4A then Vb<8 {r[3]!s:5}")
print("totals (of bags):", tot)
