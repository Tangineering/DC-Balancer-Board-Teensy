"""
sdp_ems_node.py — SDP Energy Management ROS 2 Node
UC Davis Future Mobility Lab | Scaled FCHEV Platform
Rev: 2026-03-16A

ROS 2 Jazzy node. Subscribes to /vehicle_state and /drive_cycle,
publishes /ems_command and /ems_diagnostics.

USING_STD_MSGS = True  -> uses only std_msgs (no custom msg package needed)
USING_STD_MSGS = False -> uses fchev_msgs (cleaner, recommended long-term)

Entry point in setup.py:
    'sdp_ems_node = fchev_ems.sdp_ems_node:main'
"""

import time
from pathlib import Path
import numpy as np
import scipy.io
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from std_msgs.msg import Float32MultiArray, Float64MultiArray

USING_STD_MSGS = True

SOC_MIN=0.30; SOC_MAX=0.80; SOC_BINS=250; SOC_REF=0.55
PDEM_MIN=-54.0; PDEM_MAX=150.0; PDEM_BINS=50
P_FC_MAX=24.0; P_BATT_MAX=125.0; P_BATT_MIN=-54.0
Em=7.4; Q_AH=8.0; ETA_FC=0.40; Q_LHV_H2=120000; GAMMA=0.95; ALPHA=500; U_STEPS=50
MODE_HYBRID=0; MODE_FC_ONLY=1; MODE_BATT=2; MODE_CHARGE=3; MODE_SAFE=4
SOC_LOW_ENTER=0.32; SOC_LOW_EXIT=0.35; SOC_HIGH_ENTER=0.78; SOC_HIGH_EXIT=0.75


class SDPController:
    def __init__(self, cost_to_go_path, alpha=ALPHA):
        mat = scipy.io.loadmat(cost_to_go_path)
        self.J         = mat["cost_J"].astype(float)
        self.soc_grid  = np.linspace(SOC_MIN,  SOC_MAX,  SOC_BINS)
        self.pdem_grid = np.linspace(PDEM_MIN, PDEM_MAX, PDEM_BINS)
        self.u_grid    = np.linspace(0, P_FC_MAX, U_STEPS)
        self.alpha     = alpha
        if self.J.shape != (SOC_BINS, PDEM_BINS):
            raise ValueError(f"J shape {self.J.shape} wrong — use CostToGo_J_scaled_2026-03-16A.mat")

    def step(self, P_dem, SOC):
        t0 = time.perf_counter()
        soc_clamped = SOC < SOC_MIN or SOC > SOC_MAX
        SOC = float(np.clip(SOC, SOC_MIN, SOC_MAX))
        pd_idx = int(np.argmin(np.abs(self.pdem_grid - np.clip(P_dem, PDEM_MIN, PDEM_MAX))))
        P_batt   = P_dem - self.u_grid
        SOC_next = SOC - (P_batt/Em)/(3600.0*Q_AH)
        feas = (P_batt>=P_BATT_MIN)&(P_batt<=P_BATT_MAX)&(SOC_next>=SOC_MIN)&(SOC_next<=SOC_MAX)
        if not feas.any():
            return dict(P_fc=0.0,P_batt=P_dem,power_share=0.0,feasible=False,
                        soc_clamped=soc_clamped,solve_ms=(time.perf_counter()-t0)*1000)
        idx=np.where(feas)[0]; u_f=self.u_grid[idx]; sn_f=SOC_next[idx]
        nsi=np.array([int(np.argmin(np.abs(self.soc_grid-s))) for s in sn_f])
        fut=self.J[nsi,pd_idx]
        costs=np.where(np.isinf(fut),np.inf,u_f/(ETA_FC*Q_LHV_H2)+self.alpha*np.abs(sn_f-SOC_REF)+GAMMA*fut)
        bi=int(np.argmin(costs))
        if np.isinf(costs[bi]):
            return dict(P_fc=0.0,P_batt=P_dem,power_share=0.0,feasible=False,
                        soc_clamped=soc_clamped,solve_ms=(time.perf_counter()-t0)*1000)
        P_fc=float(u_f[bi]); share=float(np.clip(P_fc/max(abs(P_dem),1.0),0.0,1.0))
        return dict(P_fc=P_fc,P_batt=P_dem-P_fc,power_share=share,feasible=True,
                    soc_clamped=soc_clamped,solve_ms=(time.perf_counter()-t0)*1000)


class SDPEMSNode(Node):
    def __init__(self):
        super().__init__("sdp_ems_node")
        self.declare_parameter("cost_j_path", "CostToGo_J_scaled_2026-03-16A.mat")
        self.declare_parameter("alpha",       float(ALPHA))
        self.declare_parameter("control_hz",  20.0)

        cost_j = self.get_parameter("cost_j_path").value
        alpha  = self.get_parameter("alpha").value
        hz     = self.get_parameter("control_hz").value

        self.ctrl = SDPController(cost_j, alpha=alpha)
        self.get_logger().info(f"SDP loaded: {cost_j} | alpha={alpha}")

        self.SOC=0.55; self.v_actual=0.0; self.fault_flags=0
        self.state_stamp=0.0; self.v_ref=0.0; self.P_demand=0.0
        self._soc_low=False; self._soc_high=False
        self._steps=0; self._solve_sum=0.0

        qos_s = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,  history=HistoryPolicy.KEEP_LAST, depth=1)
        qos_r = QoSProfile(reliability=ReliabilityPolicy.RELIABLE,      history=HistoryPolicy.KEEP_LAST, depth=10)

        self.create_subscription(Float64MultiArray, "/vehicle_state",  self._cb_state, qos_s)
        self.create_subscription(Float64MultiArray, "/drive_cycle",    self._cb_dc,    qos_r)
        self.pub_cmd  = self.create_publisher(Float64MultiArray, "/ems_command",     qos_r)
        self.pub_diag = self.create_publisher(Float64MultiArray, "/ems_diagnostics", qos_s)
        self.create_timer(1.0/hz, self._loop)
        self.get_logger().info(f"SDPEMSNode ready | {hz:.0f}Hz | SOC=[{SOC_MIN},{SOC_MAX}]")

    def _cb_state(self, msg):
        # data=[v_actual,V_batt,I_batt,I_charge,V_fc,I_fc,V_bus,P_motor,share_echo,share_actual,droop_FC,droop_BT,charger,faults,SOC]
        if len(msg.data) < 15: return
        self.v_actual=msg.data[0]; self.SOC=msg.data[14]
        self.fault_flags=int(msg.data[13]); self.state_stamp=time.monotonic()

    def _cb_dc(self, msg):
        # data=[v_ref, P_demand, elapsed, progress]
        if len(msg.data) < 2: return
        self.v_ref=float(msg.data[0]); self.P_demand=float(msg.data[1])

    def _loop(self):
        age_ms = (time.monotonic()-self.state_stamp)*1000
        if age_ms > 500:
            self.get_logger().warn(f"State stale {age_ms:.0f}ms -> SAFE")
            self._pub(0.0,0.5,0.0,MODE_SAFE,False,0.0,0.0,False,False,0.0); return

        soc = self.SOC
        if soc < SOC_LOW_ENTER:   self._soc_low  = True
        elif soc > SOC_LOW_EXIT:  self._soc_low  = False
        if soc > SOC_HIGH_ENTER:  self._soc_high = True
        elif soc < SOC_HIGH_EXIT: self._soc_high = False

        if self.fault_flags:
            self.get_logger().warn(f"Fault 0x{self.fault_flags:02X} -> SAFE")
            self._pub(0.0,0.5,0.0,MODE_SAFE,False,0.0,0.0,False,False,0.0); return
        if self._soc_low:
            P_fc=min(self.P_demand,P_FC_MAX)
            self._pub(self.v_ref,1.0,0.0,MODE_FC_ONLY,True,P_fc,self.P_demand-P_fc,True,False,0.0); return
        if self._soc_high:
            self._pub(self.v_ref,0.0,0.0,MODE_BATT,False,0.0,self.P_demand,True,False,0.0); return

        r = self.ctrl.step(P_dem=self.P_demand, SOC=soc)
        self._steps+=1; self._solve_sum+=r["solve_ms"]
        if self._steps % 100 == 0:
            self.get_logger().info(
                f"t={self._steps/20:.0f}s SOC={soc:.3f} P_fc={r['P_fc']:.1f}W "
                f"share={r['power_share']:.2f} solve_avg={self._solve_sum/self._steps:.3f}ms")
        self._pub(self.v_ref,r["power_share"],0.0,MODE_HYBRID,True,
                  r["P_fc"],r["P_batt"],r["feasible"],r["soc_clamped"],r["solve_ms"])

    def _pub(self, v_sp, share, chg, mode, droop, P_fc, P_batt, feasible, clamped, ms):
        cmd=Float64MultiArray(); cmd.data=[v_sp,share,chg,float(mode),float(droop)]
        self.pub_cmd.publish(cmd)
        diag=Float64MultiArray(); diag.data=[P_fc,P_batt,share,float(feasible),float(clamped),ms,float(mode)]
        self.pub_diag.publish(diag)


def main(args=None):
    rclpy.init(args=args)
    node = SDPEMSNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._pub(0.0,0.5,0.0,MODE_SAFE,False,0.0,0.0,False,False,0.0)
        node.destroy_node(); rclpy.shutdown()

if __name__ == "__main__":
    main()
