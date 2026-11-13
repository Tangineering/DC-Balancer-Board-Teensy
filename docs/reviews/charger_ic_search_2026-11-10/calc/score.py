W = dict(S1=15,S2=10,S3=8,S4=8,S5=7,S6=10,S7=5,S8=6,S9=4,S10=7,S11=3,S12=5,S13=2,S14=5,S15=3,S16=2)
assert sum(W.values())==100
K=list(W)
def row(*v): return dict(zip(K,v))
P = {
 'BQ25798':  row(1,1,2,2,1,0,2,1,0,1,1,2,1,2,3,0),
 'BQ25690':  row(1,2,3,2,2,0,0,2,2,1,1,1,1,2,3,0),
 'BQ25773':  row(1,2,3,2,1,1,2,1,2,0,1,2,1,2,2,0),
 'LTC4015-B':row(1,1,3,2,1,0,3,0,1,1,2,1,1,3,2,3),
 'LTC4015-A':row(1,1,1,2,1,0,3,0,1,1,2,1,1,3,2,3),
 'RAA489110':row(1,2,1,1,1,0,2,3,0,0,1,1,1,1,2,0),
}
def tot(s,w=W):
    n=sum(w.values()); return sum(w[k]*s[k]/3 for k in K)*100/n
def show(title,P,w=W):
    print('==',title)
    b=tot(P['BQ25798'],w)
    for p,s in P.items(): print(f'  {p:10s} {tot(s,w):6.2f}  margin {tot(s,w)-b:+6.2f}')
show('base',P)
for p,s in P.items():
    print(p,' + '.join(f'{W[k]*s[k]/3:.2f}' for k in K))
import copy
# A: TI warm response bad (S1 0 for TI parts)
A=copy.deepcopy(P)
for p in ['BQ25798','BQ25690','BQ25773']: A[p]['S1']=0
show('A TI S1=0',A)
# A2: BQ25798 only bad
A2=copy.deepcopy(P); A2['BQ25798']['S1']=0; show('A2 BQ25798 S1=0',A2)
# A3: LTC S1=2 (dossier reading)
A3=copy.deepcopy(P); A3['LTC4015-B']['S1']=2; A3['LTC4015-A']['S1']=2; show('A3 LTC S1=2',A3)
# A4: all good: TI parts S1 2 after bench (cap B 2)
A4=copy.deepcopy(P)
for p in P: A4[p]['S1']=2
show('A4 all S1=2',A4)
# B: stock/cost weights zero
w=dict(W); w['S12']=0; w['S13']=0; show('B stock+cost weight 0 (renorm)',P,w)
w=dict(W); w['S12']=10; w['S13']=4; show('C stock+cost weight doubled (renorm)',P,w)
w=dict(W); w['S12']=15; w['S13']=6; show('C2 stock+cost weight x3 (renorm)',P,w)
# D: evidence caps lifted by fetch
D=copy.deepcopy(P)
D['BQ25798'].update(S12=3,S13=3); D['BQ25690'].update(S12=3,S13=2); D['BQ25773'].update(S12=3,S13=3)
D['LTC4015-B'].update(S12=3,S13=2); D['LTC4015-A'].update(S12=3,S13=2); D['RAA489110'].update(S12=2,S13=3)
show('D caps lifted (optimistic fetch)',D)
# E: S14 strict never-write reading
E=copy.deepcopy(P); E['BQ25690']['S14']=1; E['BQ25773']['S14']=1; show('E strict S14',E)
# F: BQ25773 S6=0 (CHG_QUAL gates or keepalive)
F=copy.deepcopy(P); F['BQ25773']['S6']=0; show('F BQ25773 S6 0',F)
# G: dossier-native scores
G=copy.deepcopy(P); G['BQ25690']['S6']=1; show('G BQ25690 S6=1 (dossier 8-adder basis)',G)
# H: compound worst for challengers
H=copy.deepcopy(P); H['BQ25690'].update(S14=1,S5=1); H['BQ25773'].update(S14=1,S6=0); show('H challengers pessimistic',H)
# I: compound best for challengers
I=copy.deepcopy(D); I['BQ25690']['S6']=1; show('I challengers optimistic (fetch + S6)',I)
# BQ25713 provisional
b13=row(1,1,2,1,1,0,2,1,0,0,1,2,1,2,2,0); print('BQ25713 provisional', round(tot(b13),2))
# 30-33 V BQ25798-class twin re-admitted by the protected-standoff reading (main document section 6.4; scoring.md section 8.6):
# best case with every non-architectural lever at its ceiling (S2 3, S12 3, S13 3); S9 stays 0, S6 and S10 as the BQ25798
tw=dict(P['BQ25798']); tw.update(S2=3,S12=3,S13=3)
print('BQ25798-class 30 V twin bound', round(tot(tw),2), ' condition-2 threshold', round(tot(P['BQ25798'])+10,2))
