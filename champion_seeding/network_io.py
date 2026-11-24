"""Reading and writing networks as CSV files, so the model can run on a real (anonymised) organisation.

Edges file: a header row with ``source`` and ``target`` columns, one working tie per row.
Teams file (optional): a header row with ``id`` and ``team`` columns, one person per row.
"""

import csv

from . import model


def _read_rows(path, required):
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            fields = [f.strip().lower() for f in (reader.fieldnames or [])]
            missing = [c for c in required if c not in fields]
            if missing:
                raise ValueError("%s needs the column(s): %s" % (path, ", ".join(missing)))
            rows = []
            for row in reader:
                rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in row.items()})
            return rows
    except OSError as err:
        raise ValueError("Could not read %s: %s" % (path, err.strerror))


def load_network(edges_path, teams_path=None, seed=7):
    """Builds a network from CSV files. Returns (net, ids, team_names)."""
    edge_rows = _read_rows(edges_path, ["source", "target"])
    pairs = []
    ids = set()
    for row in edge_rows:
        a, b = row["source"], row["target"]
        if not a or not b:
            continue
        ids.update((a, b))
        if a != b:
            pairs.append((a, b))
    teams_of = {}
    if teams_path:
        for row in _read_rows(teams_path, ["id", "team"]):
            if row["id"]:
                teams_of[row["id"]] = row["team"] or "Unassigned"
                ids.add(row["id"])
    ids = sorted(ids)
    if len(ids) < 3:
        raise ValueError("The network needs at least three people")
    index = {pid: i for i, pid in enumerate(ids)}
    names = sorted(set(teams_of.get(pid, "Unassigned") for pid in ids))
    team_index = {name: k for k, name in enumerate(names)}
    team = [team_index[teams_of.get(pid, "Unassigned")] for pid in ids]
    adj = [set() for _ in ids]
    for a, b in pairs:
        adj[index[a]].add(index[b])
        adj[index[b]].add(index[a])
    adj = [sorted(s) for s in adj]
    rng = model.Rng(model.mix_seed(seed, model.CONSTANTS["networkSalt"]))
    c = model.CONSTANTS
    need = [c["thresholdLow"] + c["thresholdSpan"] * rng.uniform() for _ in ids]
    suit = [rng.uniform() for _ in ids]
    return model.finish_network(adj, team, need, suit), ids, names


def export_network(net, edges_path, teams_path):
    """Writes a network (for example a synthetic one) as the two CSV files that ``load_network`` reads."""
    ids = ["P%03d" % (i + 1) for i in range(net["size"])]
    with open(edges_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "target"])
        for i, nbrs in enumerate(net["adj"]):
            for j in nbrs:
                if j > i:
                    w.writerow([ids[i], ids[j]])
    with open(teams_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "team"])
        for i in range(net["size"]):
            w.writerow([ids[i], "Team %02d" % (net["team"][i] + 1)])
    return ids
