import glob,os,sys
from mcap_ros2.reader import read_ros2_messages
VS = ["v_actual","V_batt","I_batt","I_charge","V_fc","I_fc","V_bus","V_rgn","V_chg","power_share_actual"]
for d in sorted(glob.glob(sys.argv[1]+'/rosbag_*')):
    f=glob.glob(d+'/*.mcap')
    if not f: continue
    ib=[];vb=[];mv=[]
    for m in read_ros2_messages(f[0], topics=['/vehicle_state']):
        x=list(m.ros_msg.data)
        if len(x)<10: continue
        ib.append(x[2]); vb.append(x[1]); mv.append(abs(x[0]))
    if not ib: continue
    n=len(ib); mov=[i for i,v in zip(ib,mv) if v>0.05]
    print(f"{os.path.basename(d):45s} n {n:6d} I_batt max {max(ib):5.2f} A  >1.0A {100*sum(1 for i in ib if i>1.0)/n:5.1f} %  "
          f"100ms-runs>1A {sum(1 for k in range(len(ib)-5) if all(ib[k+j]>1.0 for j in range(5)))}  V_batt median {sorted(vb)[n//2]:.2f}  <8.0V {100*sum(1 for v in vb if 1<v<8.0)/n:5.1f} %")
