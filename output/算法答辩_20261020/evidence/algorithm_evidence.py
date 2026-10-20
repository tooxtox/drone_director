import sys,json,math,random
from pathlib import Path
root=next(p for p in [Path.cwd(),*Path(__file__).resolve().parents] if (p/'pyproject.toml').is_file() and (p/'algorithms').is_dir());sys.path.insert(0,str(root))
import networkx as nx
from algorithms.path_planning import CostWeights,PlanningContext,plan_path
from core.models import Position3D
g=nx.DiGraph()
for name,xyz in {'S':(100,100,120),'T':(1100,100,120),'D':(600,600,120)}.items():g.add_node(name,position=Position3D(x=xyz[0],y=xyz[1],z=xyz[2]))
for a,b in [('S','T'),('S','D'),('D','T')]:g.add_edge(a,b,capacity=10,current_flow=0,risk_level=1 if (a,b)==('S','T') else 0)
rows=[]
for risk in [0,0.2,0.5,1,2,3]:
 w=CostWeights(distance=1,risk=risk,energy=0,congestion=0,weather=0)
 result=plan_path('S','T',PlanningContext(g),w)
 rows.append({'risk_weight':risk,'route':result.node_ids,'distance_m':result.distance_m,'cost':result.total_cost,'direct_cost':1+risk,'detour_cost':math.sqrt(2)})
rng=random.Random(28);errors=[]
for trial in range(100):
 graph=nx.DiGraph()
 for i in range(24):graph.add_node(str(i),position=Position3D(x=rng.uniform(0,2000),y=rng.uniform(0,2000),z=rng.uniform(50,180)))
 for i in range(24):
  for j in range(24):
   if i!=j and (j==i+1 or rng.random()<.12):
    a,b=graph.nodes[str(i)]['position'],graph.nodes[str(j)]['position'];d=a.distance_to(b);r=rng.random();f=rng.randrange(10)
    c=d/1000*(.6+2.7*r+1.8*f/10+.9)+.9*4*max(0,b.z-a.z)/1000
    graph.add_edge(str(i),str(j),distance=d,risk_level=r,capacity=10,current_flow=f,oracle=c)
 for target in ['7','14','23']:
  p=plan_path('0',target,PlanningContext(graph),CostWeights(distance=.6,risk=2.7,congestion=1.8,energy=.9,weather=0))
  errors.append(abs(p.total_cost-nx.dijkstra_path_length(graph,'0',target,weight='oracle')))
data={'weight_sensitivity':rows,'oracle_check':{'random_seed':28,'graphs':100,'nodes_per_graph':24,'queries':len(errors),'max_abs_cost_error':max(errors),'weather_weight':0,'scope':'非负权重静态随机有向图，未覆盖城市几何与天气障碍'}}
(root/'.codex-build/20261020/reports/algorithm.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
print(json.dumps(data,ensure_ascii=False,indent=2))
