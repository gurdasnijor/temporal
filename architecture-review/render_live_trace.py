#!/usr/bin/env python3
"""Render the recorded Zinnia span parent tree."""

import json
import pathlib
import subprocess


HERE = pathlib.Path(__file__).resolve().parent
TRACE = json.loads((HERE / "zinnia-poll-trace.json").read_text())
COLORS = {
    "io.temporal.frontend": "#dcecfb",
    "io.temporal.matching": "#f5d98a",
    "io.temporal.history": "#dbf0dc",
}


def quoted(value):
    return json.dumps(value)


lines = [
    "digraph G {",
    'graph [rankdir=TB, bgcolor="white", pad=0.3, nodesep=0.3, ranksep=0.45];',
    'node [shape=box, style="rounded,filled", fontname="Helvetica", color="#54677a"];',
    'edge [color="#516a82", arrowsize=0.7];',
]
span_ids = {span["span_id"] for span in TRACE["spans"]}
for span in TRACE["spans"]:
    name = span["name"].split("/")[-1]
    label = f'{span["service"].removeprefix("io.temporal.")} / {span["kind"]}\n{name}\n{span["duration_ms"]:,.2f} ms'
    lines.append(
        f'{quoted(span["span_id"])} [label={quoted(label)}, fillcolor={quoted(COLORS[span["service"]])}];'
    )
    if span["parent_span_id"] in span_ids:
        lines.append(f'{quoted(span["parent_span_id"])} -> {quoted(span["span_id"])};')
lines.append("}")
dot = HERE / "zinnia-poll-trace.dot"
dot.write_text("\n".join(lines) + "\n")
for format_name in ("svg", "png"):
    subprocess.run(
        ["dot", f"-T{format_name}", str(dot), "-o", str(HERE / f"zinnia-poll-trace.{format_name}")],
        check=True,
    )

template = (HERE / "trace_viewer_template.html").read_text()
embedded = json.dumps(TRACE, separators=(",", ":")).replace("<", "\\u003c")
(HERE / "zinnia-poll-timeline.html").write_text(template.replace("__TRACE_JSON__", embedded))
