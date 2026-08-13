"""Create local contact sheets for structured shot semantic review."""
from __future__ import annotations
import argparse, json, subprocess, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from story_auto.core.artifacts import atomic_write_json, read_json

ap=argparse.ArgumentParser();ap.add_argument("project_root",type=Path);args=ap.parse_args();root=args.project_root.resolve();out=root/"output"/"semantic_qc";out.mkdir(parents=True,exist_ok=True)
requests=read_json(root/"output/generation_requests.json")["requests"];manifest={x.get("request_id"):x for x in read_json(root/"output/generation_manifest.json")["requests"]};shots={x["shot_id"]:x for x in read_json(root/"output/shot_plan.json")["shots"]}
rows=[]
for request in [x for x in requests if x.get("purpose")=="SHOT"]:
    entry=manifest.get(request["request_id"],{});selected=entry.get("selected_asset") or {};source=root/str(selected.get("path",""));preview=out/f"{request['request_id']}.jpg"
    if request["media_type"]=="VIDEO": subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-ss","4","-i",str(source),"-frames:v","1",str(preview)],check=True)
    else:
        with Image.open(source) as image: image.convert("RGB").save(preview,quality=90)
    shot=shots[request["shot_id"]]; rows.append({"request_id":request["request_id"],"shot_id":request["shot_id"],"part_index":request.get("part_index",1),"start":request.get("target_start",shot["start"]),"end":request.get("target_end",shot["end"]),"preview":preview.relative_to(root).as_posix(),"asset":selected.get("path"),"sha256":selected.get("sha256"),"expected":{"subject":shot.get("subject"),"action":shot.get("action"),"location":shot.get("location_id"),"characters":shot.get("character_ids",[]),"props":shot.get("prop_ids",[]),"atmospheric":bool(shot.get("atmospheric"))}})
font=ImageFont.load_default()
for page_start in range(0,len(rows),6):
    page=rows[page_start:page_start+6]; canvas=Image.new("RGB",(1200,1500),"white");draw=ImageDraw.Draw(canvas)
    for i,row in enumerate(page):
        x=(i%2)*600;y=(i//2)*500
        with Image.open(root/row["preview"]) as im:
            im.thumbnail((570,340));canvas.paste(im,(x+15,y+15))
        label=f"{row['shot_id']} part {row['part_index']}  {row['start']:.1f}-{row['end']:.1f}s\n{row['request_id']}\nExpected: {row['expected']['subject']} - {row['expected']['action']}".encode("ascii","replace").decode()
        draw.multiline_text((x+15,y+365),"\n".join(textwrap.wrap(label,88)),fill="black",font=font,spacing=3)
    canvas.save(out/f"contact_sheet_{page_start//6+1:02d}.jpg",quality=90)
atomic_write_json(out/"semantic_qc_index.json",{"rows":rows,"contact_sheets":[f"output/semantic_qc/contact_sheet_{i+1:02d}.jpg" for i in range((len(rows)+5)//6)]})
print({"shots":len(rows),"sheets":(len(rows)+5)//6})
