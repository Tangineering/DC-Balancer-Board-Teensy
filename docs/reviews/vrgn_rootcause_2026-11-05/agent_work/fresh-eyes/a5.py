rows=[(7.0191,5.9495,6.8382),(9.7355,8.5561,8.7205),(13.1988,12.2659,11.7942),(14.5033,14.1852,12.8557),(15.1702,14.54,13.0082),(15.5144,15.1902,13.2425),(15.9229,15.8328,13.4927)]
for vb,vc,vr in rows:
    n=vr/8.87
    def leak(vm): return ((vm-n)/78.7e3 - n/10e3)*1e6
    print('node %.3f V  leak(uA) if Vmot=Vbus %.1f  if Vmot=Vchg %.1f   resistor-50k would be %.1f'%(n,leak(vb),leak(vc),n/49.3e3*1e6))
