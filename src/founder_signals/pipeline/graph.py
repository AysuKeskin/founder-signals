from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape

from ..logging_utils import RunLogger
from ..schema import Profile, Stage, Status, ToolResult
from ..store import Store


def _slug(prefix: str, value: str) -> str:
    return f"{prefix}:" + "".join(c.lower() if c.isalnum() else "-" for c in value).strip("-")


def build_graph(profiles: list[Profile]) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def add_node(nid: str, label: str, kind: str) -> str:
        nodes.setdefault(nid, {"id": nid, "label": label, "kind": kind})
        return nid

    sector_members: dict[str, list[str]] = {}

    for p in profiles:
        name = p.full_name.value or p.id
        fid = add_node(f"founder:{p.id}", name, "founder")

        company = p.current_company.value
        if company:
            cid = add_node(_slug("company", company), company, "company")
            edges.append({"source": fid, "target": cid, "rel": "FOUNDED"})

        region = p.region.value
        if region and region != "unknown":
            rid = add_node(f"region:{region}", region, "region")
            edges.append({"source": fid, "target": rid, "rel": "IN_REGION"})

        sectors = p.sectors.value if isinstance(p.sectors.value, list) else []
        for sec in sectors:
            sid = add_node(_slug("sector", sec), sec, "sector")
            edges.append({"source": fid, "target": sid, "rel": "IN_SECTOR"})
            sector_members.setdefault(sec, []).append(fid)

    clusters = [
        {"sector": sec, "size": len(members), "founders": members}
        for sec, members in sector_members.items() if len(members) >= 2
    ]
    clusters.sort(key=lambda c: c["size"], reverse=True)

    stats = {
        "founders": sum(1 for n in nodes.values() if n["kind"] == "founder"),
        "companies": sum(1 for n in nodes.values() if n["kind"] == "company"),
        "sectors": sum(1 for n in nodes.values() if n["kind"] == "sector"),
        "regions": sum(1 for n in nodes.values() if n["kind"] == "region"),
        "edges": len(edges),
        "top_sectors": [{"sector": c["sector"], "founders": c["size"]}
                        for c in clusters[:5]],
    }
    return {"nodes": list(nodes.values()), "edges": edges,
            "clusters": clusters, "stats": stats}


_NODE_COLOR = {"founder": "#2563eb", "company": "#16a34a",
               "sector": "#d97706", "region": "#9333ea"}


def _to_html(graph: dict) -> str:
    nodes = [{"id": n["id"], "label": n["label"], "group": n["kind"],
              "color": _NODE_COLOR.get(n["kind"], "#888")} for n in graph["nodes"]]
    edges = [{"from": e["source"], "to": e["target"]} for e in graph["edges"]]
    s = graph["stats"]
    legend = " &nbsp; ".join(
        f'<b style="color:{_NODE_COLOR[k]}">●</b> {k}' for k in _NODE_COLOR)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Founder Signals — relationship graph</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>body{{font:14px system-ui;margin:0}}#bar{{padding:8px 12px;background:#f3f4f6}}
#net{{width:100vw;height:92vh}}</style></head><body>
<div id="bar"><b>Founder Signals</b> — {s['founders']} founders · {s['companies']} companies ·
{s['sectors']} sectors · {s['edges']} edges &nbsp;&nbsp; {legend}</div>
<div id="net"></div>
<script>
const nodes=new vis.DataSet({json.dumps(nodes, ensure_ascii=False)});
const edges=new vis.DataSet({json.dumps(edges, ensure_ascii=False)});
new vis.Network(document.getElementById('net'),{{nodes,edges}},{{
  nodes:{{shape:'dot',size:12,font:{{size:11}}}},
  edges:{{color:{{color:'#cbd5e1'}},smooth:false}},
  physics:{{stabilization:true,barnesHut:{{gravitationalConstant:-8000,springLength:120}}}}
}});
</script></body></html>"""


def _to_graphml(graph: dict) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '<key id="label" for="node" attr.name="label" attr.type="string"/>',
        '<key id="kind" for="node" attr.name="kind" attr.type="string"/>',
        '<key id="rel" for="edge" attr.name="rel" attr.type="string"/>',
        '<graph edgedefault="directed">',
    ]
    for n in graph["nodes"]:
        lines.append(
            f'<node id="{escape(n["id"])}">'
            f'<data key="label">{escape(str(n["label"]))}</data>'
            f'<data key="kind">{escape(n["kind"])}</data></node>'
        )
    for i, e in enumerate(graph["edges"]):
        lines.append(
            f'<edge id="e{i}" source="{escape(e["source"])}" target="{escape(e["target"])}">'
            f'<data key="rel">{escape(e["rel"])}</data></edge>'
        )
    lines += ["</graph>", "</graphml>"]
    return "\n".join(lines)


def run_graph(store: Store, logger: RunLogger,
              out_dir: Optional[Path] = None, top: Optional[int] = None) -> ToolResult[dict]:
    start = time.monotonic()
    profiles = store.ranked(limit=top) if top else store.ranked()
    profiles = [p for p in profiles if (p.rank_score or 0) > 0]

    with logger.stage(Stage.GRAPH.value, founders=len(profiles)):
        graph = build_graph(profiles)
        out_dir = out_dir or (store.path.parent / "exports")
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / "graph.json"
        graphml_path = out_dir / "graph.graphml"
        html_path = out_dir / "graph.html"
        json_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
        graphml_path.write_text(_to_graphml(graph), encoding="utf-8")
        html_path.write_text(_to_html(graph), encoding="utf-8")

    elapsed = int((time.monotonic() - start) * 1000)
    data = {**graph["stats"], "clusters": len(graph["clusters"]),
            "json": str(json_path), "graphml": str(graphml_path),
            "html": str(html_path)}
    status = Status.OK if profiles else Status.PARTIAL
    return ToolResult(status=status, stage=Stage.GRAPH, data=data,
                      count=graph["stats"]["founders"], run_id=logger.run_id,
                      elapsed_ms=elapsed,
                      message=f"graph: {graph['stats']['founders']} founders, "
                              f"{graph['stats']['edges']} edges")


def connections(store: Store, profile_id: str) -> ToolResult[dict]:
    target = store.get(profile_id)
    if not target:
        return ToolResult.error(Stage.GRAPH, f"profile not found: {profile_id}")

    t_sectors = set(target.sectors.value or []) if isinstance(target.sectors.value, list) else set()
    t_region = target.region.value
    t_company = target.current_company.value

    related = []
    for p in store.ranked():
        if p.id == target.id or (p.rank_score or 0) <= 0:
            continue
        p_sectors = set(p.sectors.value or []) if isinstance(p.sectors.value, list) else set()
        shared_sectors = sorted(t_sectors & p_sectors)
        same_region = bool(t_region) and p.region.value == t_region
        same_company = bool(t_company) and p.current_company.value == t_company
        if shared_sectors or same_company:
            related.append({
                "id": p.id, "name": p.full_name.value,
                "shared_sectors": shared_sectors,
                "same_region": same_region, "same_company": same_company,
            })
    related.sort(key=lambda r: (r["same_company"], len(r["shared_sectors"])), reverse=True)
    return ToolResult.ok(Stage.GRAPH, {"founder": target.full_name.value,
                                       "connections": related[:25],
                                       "total": len(related)})
