"""Convert ComfyUI canvas workflows with blueprint subgraphs to API prompts.

This targets the native ComfyUI workflow format used by the supplied MiniMax H3
workflow. It deliberately treats the JSON as data and only reads graph fields.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _links(graph):
    result = {}
    for item in graph.get("links", []):
        if isinstance(item, dict):
            result[item["id"]] = item
        else:
            result[item[0]] = {"id": item[0], "origin_id": item[1], "origin_slot": item[2],
                               "target_id": item[3], "target_slot": item[4], "type": item[5]}
    return result


def _widget_values(node):
    values = iter(node.get("widgets_values", []))
    result = {}
    for inp in node.get("inputs", []):
        widget = inp.get("widget")
        if widget:
            name = widget.get("name", inp.get("name")) if isinstance(widget, dict) else inp.get("name")
            try:
                result[name] = next(values)
            except StopIteration:
                break
    return result


def _interface_values(instance, subgraph, overrides):
    # Subgraph instance widgets are stored in interface order. The outer node's
    # visible input metadata only describes linked inputs (e.g. width/height),
    # so using _widget_values here would shift the values by one or two slots.
    values = {}
    non_image = [x["name"] for x in subgraph.get("inputs", []) if x["name"] not in {"first_frame", "last_frame"}]
    raw = instance.get("widgets_values", [])
    # Canvas subgraph instances store exposed widget values in interface order.
    for name, value in zip(non_image, raw):
        values.setdefault(name, value)
    values.update(overrides)
    return values


def convert(canvas_path, prompt=None, duration=None, seed=None, first_frame_node=None,
            width=1344, height=768):
    canvas = load(canvas_path) if isinstance(canvas_path, (str, Path)) else copy.deepcopy(canvas_path)
    definitions = {x["id"]: x for x in canvas.get("definitions", {}).get("subgraphs", [])}
    api = {}
    output_refs = {}
    node_aliases = {}

    def add_node(node, prefix, graph, external=None, subgraph_id=None):
        if node["type"] in {"MarkdownNote", "Note", "PrimitiveNode"}:
            return None
        node_id = str(node["id"] if not prefix else f"{prefix}_{node['id']}")
        inputs = {}
        link_map = _links(graph)
        widgets = _widget_values(node)
        for inp in node.get("inputs", []):
            name = inp.get("name")
            link_id = inp.get("link")
            if link_id is not None and link_id in link_map:
                link = link_map[link_id]
                source = link["origin_id"]
                if source == -10 and external is not None:
                    values = external
                    if name in values and values[name] is not None:
                        inputs[name] = values[name]
                    continue
                if source == -20 and external is not None:
                    continue
                source_id = str(source if not prefix else f"{prefix}_{source}")
                inputs[name] = [source_id, link["origin_slot"]]
            elif name in widgets:
                inputs[name] = widgets[name]
        api[node_id] = {"class_type": node["type"], "inputs": inputs}
        node_aliases[(prefix, node["id"])] = node_id
        return node_id

    def expand_instance(instance, subgraph):
        prefix = str(instance["id"])
        values = _interface_values(instance, subgraph, {
            "prompt": prompt, "value_1": duration, "noise_seed": seed,
        })
        external_refs = {}
        outer_link_map = _links(canvas)
        for inp in instance.get("inputs", []):
            if inp.get("link") in outer_link_map:
                link = outer_link_map[inp["link"]]
                external_refs[inp["name"]] = [str(link["origin_id"]), link["origin_slot"]]
        inner_links = _links(subgraph)
        for node in subgraph.get("nodes", []):
            if node["id"] < 0:
                continue
            add_node(node, prefix, subgraph, external=values, subgraph_id=subgraph["id"])
        # Inputs connected to the subgraph interface must become literal values.
        for link in inner_links.values():
            if link["origin_id"] == -10:
                target_id = str(f"{prefix}_{link['target_id']}")
                target = api[target_id]
                target_node = next(x for x in subgraph["nodes"] if x["id"] == link["target_id"])
                input_name = target_node["inputs"][link["target_slot"]]["name"]
                interface = next(x for x in subgraph["inputs"] if link["id"] in x.get("linkIds", []))
                if interface["name"] in external_refs:
                    target["inputs"][input_name] = external_refs[interface["name"]]
                    continue
                value = values.get(interface["name"])
                if value is not None:
                    target["inputs"][input_name] = value
        # Optional automated first-frame loader for chained shots.
        if first_frame_node:
            load_id = f"{prefix}_auto_first_frame"
            api[load_id] = {"class_type": "LoadImage", "inputs": {"image": first_frame_node}}
            api[f"{prefix}_104"]["inputs"]["first_frame"] = [load_id, 0]
        # The subgraph output is the source of the outer instance output.
        out_link = _links(subgraph)[subgraph["outputs"][0]["linkIds"][0]]
        return str(f"{prefix}_{out_link['origin_id']}"), out_link["origin_slot"]

    outer_links = _links(canvas)
    for node in canvas.get("nodes", []):
        if node["type"] in definitions:
            output_refs[node["id"]] = expand_instance(node, definitions[node["type"]])
        else:
            add_node(node, "", canvas)

    # Rewire outer edges that used the subgraph instance as their origin.
    for link in outer_links.values():
        origin = link["origin_id"]
        if origin in output_refs:
            target_id = str(link["target_id"])
            target = api[target_id]
            target_node = next(x for x in canvas["nodes"] if x["id"] == link["target_id"])
            input_name = target_node["inputs"][link["target_slot"]]["name"]
            target["inputs"][input_name] = list(output_refs[origin])

    # The supplied H3 canvas uses utility nodes only to expose UI controls. Keep
    # the API prompt self-contained by resolving those controls to literals.
    for node_id, node in list(api.items()):
        cls = node["class_type"]
        if cls == "KSamplerSelect":
            node["inputs"] = {"sampler_name": "res_multistep"}
        elif cls == "UNETLoader":
            node["inputs"]["weight_dtype"] = "default"
        elif cls == "CLIPLoader":
            node["inputs"]["type"] = "minimax"
        elif cls == "BasicScheduler":
            node["inputs"].update({"scheduler": "simple", "steps": 20, "denoise": 1.0})
        elif cls == "CreateVideo":
            node["inputs"].update({"fps": 24.0, "bit_depth": 8})
        elif cls == "SaveVideo":
            # ComfyUI's legacy /prompt endpoint expects the dynamic combo's
            # selected key as a scalar; nested v3 values are ignored there.
            node["inputs"].update({"format": "auto", "codec": "auto"})
        elif cls == "MiniMaxH3ImageToVideo":
            seconds = float(duration or 5)
            frames = max(5, round(seconds * 24))
            while frames % 17 != 5:
                frames += 1
            node["inputs"]["width"] = width
            node["inputs"]["height"] = height
            node["inputs"]["length"] = frames
    for node_id in [k for k, v in api.items() if v["class_type"] in {"ResolutionSelector", "ComfyMathExpression", "PrimitiveFloat", "MarkdownNote", "Note"}]:
        api.pop(node_id, None)
    return api


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    args.output.write_text(json.dumps(convert(args.workflow), ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
