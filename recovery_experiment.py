"""Reproduce three explicitly labelled toy cases; no statistical generalization."""
import copy
import csv
import json
import math
from pathlib import Path
from coverage_alternatives import compare_recovery, measure
from coverage_alternatives_checks import multi_example, source
from wind_buffer_checks import example
from wind_buffer import apply_buffer
from scene import generate


def run(output=None):
    out=Path(output or Path(__file__).resolve().parent/'examples/multi-sensitive-recovery')
    out.mkdir(parents=True,exist_ok=True)
    base,z=example()
    cases={'single-edge':apply_buffer(base,[z],3.5,2,math.pi)['scene'],
           'dense-staggered':multi_example()}
    dense=generate(dict(rows=4,trees_per_row=5,row_spacing=4,plant_spacing=3))
    cases['dense-overlapping']=apply_buffer(dense,[source('overlap-a',9.8,0,10.5,8),
        source('overlap-b',10.2,5,11,14)],1.3,2,math.pi)['scene']
    summary=[]
    for name,scene in cases.items():
        saved=copy.deepcopy(scene)
        result=compare_recovery(scene,dict(wind_speed=2,wind_direction=math.pi),.1,60)
        assert scene==saved
        (out/(name+'.scene.json')).write_text(json.dumps(scene,ensure_ascii=False,indent=2),encoding='utf8')
        if result['status']=='success':
            for row in result['alternatives']:
                fine,_=measure(scene,row['plan'],.05)
                row['fine_grid_005']=fine
                summary.append(dict(case=name,strategy=row['strategy'],duration=row['duration'],
                    extra_miss_010=row['extra_miss'],extra_miss_005=fine['extra_miss'],
                    restricted_010=row['restricted_area'],restricted_005=fine['restricted_area'],
                    repeated_cells_010=row['repeated_cells'],repeated_area_010=row['repeated_area'],spray_amount=row['spray_amount'],
                    added_seconds=row['added_seconds'],illegal_count=row['illegal_count']))
        (out/(name+'.comparison.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(name,[(r['strategy'],round(r['extra_miss'],3),round(r['duration'],3))
                    for r in result.get('alternatives',[])],flush=True)
    if summary:
        with (out/'summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(summary[0]));writer.writeheader();writer.writerows(summary)
    return summary

if __name__=='__main__':run()
