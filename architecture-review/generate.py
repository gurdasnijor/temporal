#!/usr/bin/env python3
"""Generate static architecture views from the two local Go repositories."""

import collections
import json
import pathlib
import re
import subprocess


HERE = pathlib.Path(__file__).resolve().parent
OSS = HERE.parent
SAAS = OSS.parent / "saas-temporal"
OSS_PREFIX = "go.temporal.io/server/"
SAAS_PREFIX = "github.com/temporalio/saas-temporal/"


def quote(value):
    return json.dumps(value)


def write_graph(name, body):
    dot = HERE / f"{name}.dot"
    dot.write_text(body)
    subprocess.run(["dot", "-Tsvg", str(dot), "-o", str(HERE / f"{name}.svg")], check=True)
    subprocess.run(["dot", "-Tpng", "-Gdpi=140", str(dot), "-o", str(HERE / f"{name}.png")], check=True)


def go_packages(root, patterns):
    result = subprocess.run(
        ["go", "list", "-json", *patterns], cwd=root, capture_output=True, text=True, check=True
    )
    decoder = json.JSONDecoder()
    packages = []
    value = result.stdout
    pos = 0
    while pos < len(value):
        match = re.search(r"\S", value[pos:])
        if match is None:
            break
        pos += match.start()
        package, length = decoder.raw_decode(value[pos:])
        packages.append(package)
        pos += length
    return packages


def section(path, prefix):
    if not path.startswith(prefix):
        return None
    parts = path[len(prefix):].split("/")
    if parts[0] == "service" and len(parts) > 1:
        return "service/" + parts[1]
    if parts[0] == "client" and len(parts) > 1:
        return "client/" + parts[1]
    if parts[0] == "common" and len(parts) > 1:
        if parts[1] == "persistence" and len(parts) > 2:
            return "common/persistence/" + parts[2]
        return "common/" + parts[1]
    if parts[0] == "cds" and len(parts) > 1:
        if parts[1] == "storage" and len(parts) > 2:
            return "cds/storage/" + parts[2]
        return "cds/" + parts[1]
    if parts[0] == "walker" and len(parts) > 1:
        if parts[1] == "datanode" and len(parts) > 2:
            return "walker/datanode/" + parts[2]
        return "walker/" + parts[1]
    return parts[0]


def matching_imports(packages):
    package = next(p for p in packages if p["ImportPath"] == OSS_PREFIX + "service/matching")
    targets = sorted(i for i in package["Imports"] if i.startswith(OSS_PREFIX))
    lines = [
        "digraph G {",
        'graph [rankdir=LR, bgcolor="white", pad=0.25];',
        'node [shape=box, style="rounded,filled", fillcolor="#e5f1ff", color="#4c78a8", fontname="Helvetica"];',
        'edge [color="#8a9bae", arrowsize=0.7];',
        'matching [label="service/matching", fillcolor="#f5d98a"];',
    ]
    for index, target in enumerate(targets):
        lines.append(f'p{index} [label={quote(target[len(OSS_PREFIX):])}];')
        lines.append(f'matching -> p{index};')
    lines.append("}")
    write_graph("oss-matching-direct-imports", "\n".join(lines))
    return len(targets)


def aggregated_imports(name, packages, prefix, allowed):
    counts = collections.Counter()
    for package in packages:
        source = section(package["ImportPath"], prefix)
        if source not in allowed:
            continue
        for imported in package.get("Imports", []):
            target = section(imported, prefix)
            if target in allowed and source != target:
                counts[source, target] += 1
    lines = [
        "digraph G {",
        'graph [rankdir=LR, bgcolor="white", pad=0.25, overlap=false, splines=true];',
        'node [shape=box, style="rounded,filled", fillcolor="#e5f1ff", color="#4c78a8", fontname="Helvetica"];',
        'edge [color="#8a9bae", arrowsize=0.7, fontname="Helvetica", fontsize=10];',
    ]
    for node in sorted(allowed):
        lines.append(f'{quote(node)} [label={quote(node)}];')
    for (source, target), count in sorted(counts.items()):
        lines.append(f'{quote(source)} -> {quote(target)} [label={quote(str(count))}, penwidth={min(1 + count / 8, 5):.1f}];')
    lines.append("}")
    write_graph(name, "\n".join(lines))
    return counts


def curated_graphs():
    write_graph("runtime-boundaries", r'''digraph G {
graph [rankdir=LR, bgcolor="white", pad=0.3, compound=true, splines=polyline];
node [shape=box, style="rounded,filled", fontname="Helvetica", color="#54677a", fillcolor="#e8f1fa"];
edge [fontname="Helvetica", fontsize=10, color="#516a82"];
sdk [label="SDK client / worker", fillcolor="#f6e0a9"];
frontend [label="Frontend\nWorkflowService gRPC\nHTTP API / Nexus HTTP"];
history [label="History\nworkflow execution / transfer queue"];
matching [label="Matching\ntask queue partitions / long polls", fillcolor="#f5d98a"];
persist [label="OSS persistence interfaces\nTaskManager / FairTaskManager"];
history_store [label="History persistence\nexecution store"];
cassandra [label="Cassandra matching task stores", fillcolor="#f6e0a9"];
walker [label="Walker matching task stores\nnot implemented", style="rounded,dashed", fillcolor="#ffffff"];
sdk -> frontend [label="external gRPC / HTTP"];
frontend -> history [label="internal gRPC"];
frontend -> matching [label="internal gRPC: poll"];
history -> matching [label="internal gRPC: add task"];
matching -> history [label="internal gRPC: record task start"];
matching -> matching [label="partition forwarding\ninternal gRPC", color="#a57421"];
history -> history_store [label="execution persistence"];
matching -> persist [label="task queue persistence"];
persist -> cassandra [label="SaaS current matching"];
persist -> walker [label="SaaS target", style=dashed];
}''')
    write_graph("repo-layout", r'''digraph G {
graph [rankdir=LR, bgcolor="white", pad=0.3, compound=true];
node [shape=box, style="rounded,filled", fontname="Helvetica", color="#54677a", fillcolor="#e8f1fa"];
edge [fontname="Helvetica", fontsize=10, color="#516a82"];
subgraph cluster_oss {
  label="temporal  •  Go module: go.temporal.io/server";
  color="#87a8c6";
  api [label="api/ + proto/\npublic/internal RPC contracts"];
  client [label="client/\ninter-service clients"];
  services [label="service/\nfrontend • history • matching • worker"];
  common [label="common/\nshared utilities + persistence interfaces"];
  schema [label="schema/\ndatabase schemas"];
}
subgraph cluster_saas {
  label="saas-temporal  •  Go module: github.com/temporalio/saas-temporal";
  color="#c5ad76";
  cds [label="cds/export/cds/\npersistence factory"];
  storage [label="cds/storage/\nCassandra + Walker adapters"];
  subgraph cluster_walker {
    label="walker/  •  nested Go module";
    color="#d3bc87";
    walker [label="datanode/ • wkeys/ • replication/\nWalker storage system", fillcolor="#fff2d6"];
  }
}
services -> client [label="Go imports"];
services -> common [label="Go imports"];
cds -> storage [label="Go imports"];
storage -> walker [label="Go imports"];
cds -> common [label="binds persistence interfaces", style=dashed];
}''')
    write_graph("workflow-task-flow", r'''digraph G {
graph [rankdir=LR, bgcolor="white", pad=0.3, splines=polyline];
node [shape=box, style="rounded,filled", fontname="Helvetica", color="#54677a", fillcolor="#e8f1fa"];
edge [fontname="Helvetica", fontsize=10, color="#516a82"];
client [label="Client\nStartWorkflowExecution", fillcolor="#f6e0a9"];
front [label="Frontend\nvalidate + route"];
hist [label="History\nrecord workflow event"];
db [label="History store\nmutable state + transfer task"];
transfer [label="History transfer queue\nasync processor"];
add [label="Matching\nAddWorkflowTask", fillcolor="#f5d98a"];
sync [label="Sync match\nwaiting poller"];
backlog [label="Backlog\nTaskManager.CreateTasks"];
taskdb [label="Matching task store\ncurrent SaaS: Cassandra", fillcolor="#f6e0a9"];
client -> front [label="external gRPC"];
front -> hist [label="internal gRPC"];
hist -> db [label="persistence"];
db -> transfer [label="transfer task"];
transfer -> add [label="internal gRPC"];
add -> sync [label="poller present"];
add -> backlog [label="otherwise"];
backlog -> taskdb [label="persistence"];
}''')
    write_graph("worker-poll-flow", r'''digraph G {
graph [rankdir=LR, bgcolor="white", pad=0.3, splines=polyline];
node [shape=box, style="rounded,filled", fontname="Helvetica", color="#54677a", fillcolor="#e8f1fa"];
edge [fontname="Helvetica", fontsize=10, color="#516a82"];
worker [label="SDK worker\nPollWorkflowTaskQueue", fillcolor="#f6e0a9"];
front [label="Frontend\nWorkflowHandler"];
match [label="Matching\nHandler + engine", fillcolor="#f5d98a"];
partition [label="Task queue partition\nlong poll / sync match"];
backlog [label="Task queue backlog\nTaskManager.GetTasks"];
taskdb [label="Matching task store\ncurrent SaaS: Cassandra", fillcolor="#f6e0a9"];
hist [label="History\nRecordWorkflowTaskStarted"];
worker -> front [label="external gRPC"];
front -> match [label="internal gRPC"];
match -> partition [label="in process"];
partition -> backlog [label="if no sync task"];
backlog -> taskdb [label="persistence"];
partition -> hist [label="internal gRPC"];
hist -> match [label="task + history response", style=dashed];
match -> front [label="task response", style=dashed];
front -> worker [label="poll response", style=dashed];
}''')
    write_graph("saas-matching-storage-gap", r'''digraph G {
graph [rankdir=LR, bgcolor="white", pad=0.3, splines=polyline];
node [shape=box, style="rounded,filled", fontname="Helvetica", color="#54677a", fillcolor="#e8f1fa"];
edge [fontname="Helvetica", fontsize=10, color="#516a82"];
matching [label="OSS Matching\ntaskQueueDB", fillcolor="#f5d98a"];
iface [label="OSS persistence.TaskManager\nand FairTaskManager"];
factory [label="SaaS CDS factory\nmatchingTaskStore + fair"];
multi [label="MultiDBMatchingTaskStore\nqueue to Cassandra cluster"];
cass [label="Cassandra TaskStore", fillcolor="#f6e0a9"];
walkerp [label="MultiWalkerStoreProvider\nNewMatchingTaskStore: unimplemented", style="rounded,dashed", fillcolor="#ffffff"];
client [label="Walker datanode client\ngRPC", style="rounded,dashed", fillcolor="#ffffff"];
datanodes [label="Walker datanodes\nWAL + replicated state", style="rounded,dashed", fillcolor="#ffffff"];
matching -> iface [label="Create/Get/CompleteTasks"];
iface -> factory [label="SaaS implementation"];
factory -> multi [label="current"];
multi -> cass [label="storage driver"];
factory -> walkerp [label="migration path", style=dashed];
walkerp -> client [label="candidate", style=dashed];
client -> datanodes [label="gRPC", style=dashed];
}''')


def fx_inventory():
    source = (OSS / "service/matching/fx.go").read_text()
    module = source.split("var Module = fx.Options(", 1)[1].split("\n)\n", 1)[0]
    providers = re.findall(r"fx\.Provide\(([^)]+)\)", module)
    invokes = re.findall(r"fx\.Invoke\(([^)]+)\)", module)
    modules = re.findall(r"^\s*([\w.]+\.Module),?\s*$", module, re.MULTILINE)
    lines = [
        "# Matching Fx registration inventory",
        "",
        "Generated from `service/matching/fx.go` with `python3 architecture-review/generate.py`.",
        "These are registrations in the service module; they are not resolved constructor edges.",
        "",
        "## Included modules",
        "",
        *[f"- `{value}`" for value in modules],
        "",
        "## Providers",
        "",
        *[f"- `{value}`" for value in providers],
        "",
        "## Invokes",
        "",
        *[f"- `{value}`" for value in invokes],
        "",
    ]
    (HERE / "matching-fx-registration.md").write_text("\n".join(lines))


def main():
    curated_graphs()
    fx_inventory()
    oss = go_packages(OSS, ["./service/frontend/...", "./service/history/...", "./service/matching/...", "./service/worker/...", "./client/...", "./common/persistence/..."])
    direct_count = matching_imports(oss)
    oss_sections = {"service/frontend", "service/history", "service/matching", "service/worker", "client/frontend", "client/history", "client/matching", "common/persistence/client", "common/persistence"}
    oss_edges = aggregated_imports("oss-subsystem-imports", oss, OSS_PREFIX, oss_sections)
    saas = go_packages(SAAS, ["./cds/export/cds", "./cds/storage/..."])
    saas += go_packages(SAAS / "walker", ["./datanode/client", "./wkeys"])
    saas_sections = {"cds/export", "cds/storage/walkerstores", "cds/storage", "walker/datanode/client", "walker/wkeys"}
    saas_edges = aggregated_imports("saas-storage-imports", saas, SAAS_PREFIX, saas_sections)
    (HERE / "generation-stats.json").write_text(json.dumps({
        "oss_packages": len(oss), "saas_packages": len(saas),
        "matching_direct_internal_imports": direct_count,
        "oss_aggregated_edges": len(oss_edges), "saas_aggregated_edges": len(saas_edges),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
