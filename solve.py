#!/usr/bin/env python3
"""Turn-restriction-aware shortest path solver."""

from __future__ import annotations

import heapq
import json
import sys
from pathlib import Path
from typing import Any


class Network:
    def __init__(self, data: dict[str, Any]):
        self.id = data.get("id", "")
        self.nodes: dict[str, tuple[float, float]] = {}
        for node in data["nodes"]:
            node_id = node["id"]
            if node_id in self.nodes:
                raise ValueError(f"duplicate node id: {node_id}")
            self.nodes[node_id] = (node["x"], node["y"])

        edges = sorted(data["edges"], key=lambda edge: edge["id"])
        self.edge_ids: list[str] = [edge["id"] for edge in edges]
        self.edge_from: list[str] = []
        self.edge_to: list[str] = []
        self.edge_cost: list[int] = []

        edge_index = {edge_id: i for i, edge_id in enumerate(self.edge_ids)}
        self.out: dict[str, list[int]] = {node_id: [] for node_id in self.nodes}
        self.inc: dict[str, list[int]] = {node_id: [] for node_id in self.nodes}

        for i, edge in enumerate(edges):
            source = edge["from"]
            target = edge["to"]
            cost = edge["cost"]
            if source not in self.nodes or target not in self.nodes:
                raise ValueError(f"edge {edge['id']!r} references an unknown node")
            if not isinstance(cost, int) or isinstance(cost, bool) or not 1 <= cost <= 10**6:
                raise ValueError(f"edge {edge['id']!r} has an invalid cost")
            self.edge_from.append(source)
            self.edge_to.append(target)
            self.edge_cost.append(cost)
            self.out[source].append(i)
            self.inc[target].append(i)

        self.banned: set[tuple[int, int]] = set()
        for restriction in data.get("turn_restrictions", []):
            incoming = edge_index.get(restriction["in"])
            outgoing = edge_index.get(restriction["out"])
            if incoming is None or outgoing is None:
                raise ValueError("turn restriction references an unknown edge")
            if self.edge_to[incoming] != self.edge_from[outgoing]:
                raise ValueError("turn restriction does not meet at one node")
            self.banned.add((incoming, outgoing))


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def resolve_network_path(query_path: Path, network_ref: str) -> Path:
    network_path = Path(network_ref)
    if network_path.is_absolute():
        return network_path

    candidates = (
        Path.cwd() / network_path,
        Path(__file__).resolve().parent / network_path,
        query_path.resolve().parent / network_path,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def shortest_from(
    network: Network,
    source: str,
    targets: set[str] | None = None,
) -> dict[str, tuple[int | None, list[str]]]:
    """Return shortest, lexicographically smallest routes from one node."""
    if source not in network.nodes:
        raise ValueError(f"unknown source node: {source}")
    if targets:
        unknown = sorted(target for target in targets if target not in network.nodes)
        if unknown:
            raise ValueError(f"unknown target node: {unknown[0]}")

    edge_count = len(network.edge_ids)
    infinity = 10**30
    distances = [infinity] * edge_count
    parents: list[list[int] | None] = [None] * edge_count
    settled: list[int] = []
    heap: list[tuple[int, int]] = []
    node_cost: dict[str, int] = {source: 0}

    for edge in network.out.get(source, ()):
        distances[edge] = network.edge_cost[edge]
        parents[edge] = []
        heapq.heappush(heap, (distances[edge], edge))

    wanted = targets or set()
    while heap:
        if wanted and all(target in node_cost for target in wanted):
            if heap[0][0] > max(node_cost[target] for target in wanted):
                break

        distance, edge = heapq.heappop(heap)
        if distance != distances[edge]:
            continue

        settled.append(edge)
        endpoint = network.edge_to[edge]
        if endpoint not in node_cost:
            node_cost[endpoint] = distance

        for next_edge in network.out.get(endpoint, ()):
            if (edge, next_edge) in network.banned:
                continue
            new_distance = distance + network.edge_cost[next_edge]
            if new_distance < distances[next_edge]:
                distances[next_edge] = new_distance
                parents[next_edge] = [edge]
                heapq.heappush(heap, (new_distance, next_edge))
            elif new_distance == distances[next_edge] and parents[next_edge] is not None:
                parents[next_edge].append(edge)

    # A front trie gives exact lexicographic ordering of complete edge-id
    # sequences while storing every route in O(path length), not O(path^2).
    levels = max(1, edge_count.bit_length())
    trie_parent = [-1]
    trie_edge = [-1]
    trie_depth = [0]
    trie_up = [[-1] for _ in range(levels)]
    trie_child: dict[tuple[int, int], int] = {}
    labels = [-1] * edge_count

    def extend_trie(parent: int, edge: int) -> int:
        key = (parent, edge)
        node = trie_child.get(key)
        if node is not None:
            return node

        node = len(trie_parent)
        trie_child[key] = node
        trie_parent.append(parent)
        trie_edge.append(edge)
        trie_depth.append(trie_depth[parent] + 1)

        trie_up[0].append(parent)
        for level in range(1, levels):
            ancestor = trie_up[level - 1][node]
            trie_up[level].append(
                trie_up[level - 1][ancestor] if ancestor != -1 else -1
            )
        return node

    def lift(node: int, amount: int) -> int:
        level = 0
        while amount:
            if amount & 1:
                node = trie_up[level][node]
            amount >>= 1
            level += 1
        return node

    def lex_less(left: int, right: int) -> bool:
        if left == right:
            return False

        original_left, original_right = left, right
        left_depth = trie_depth[left]
        right_depth = trie_depth[right]
        if left_depth > right_depth:
            left = lift(left, left_depth - right_depth)
        elif right_depth > left_depth:
            right = lift(right, right_depth - left_depth)

        if left == right:
            return trie_depth[original_left] < trie_depth[original_right]

        for level in range(levels - 1, -1, -1):
            if trie_up[level][left] != trie_up[level][right]:
                left = trie_up[level][left]
                right = trie_up[level][right]

        return trie_edge[left] < trie_edge[right]

    for edge in settled:
        best_parent = 0 if network.edge_from[edge] == source else -1
        for parent in parents[edge] or ():
            candidate = labels[parent]
            if best_parent == -1 or lex_less(candidate, best_parent):
                best_parent = candidate
        if best_parent != -1:
            labels[edge] = extend_trie(best_parent, edge)

    finalists: dict[str, list[int]] = {}
    for edge in settled:
        endpoint = network.edge_to[edge]
        if distances[edge] == node_cost.get(endpoint):
            finalists.setdefault(endpoint, []).append(edge)

    path_cache: dict[str, tuple[int | None, list[str]]] = {}

    def route_to(target: str) -> tuple[int | None, list[str]]:
        if target in path_cache:
            return path_cache[target]

        if target == source:
            result: tuple[int | None, list[str]] = (0, [])
            path_cache[target] = result
            return result

        cost = node_cost.get(target)
        if cost is None:
            result = (None, [])
            path_cache[target] = result
            return result

        winner = -1
        for edge in finalists.get(target, ()):
            if winner == -1 or lex_less(labels[edge], labels[winner]):
                winner = edge

        route_nodes: list[int] = []
        trie_node = labels[winner]
        while trie_node != 0:
            route_nodes.append(trie_edge[trie_node])
            trie_node = trie_parent[trie_node]
        route_nodes.reverse()
        result = (cost, [network.edge_ids[edge] for edge in route_nodes])
        path_cache[target] = result
        return result

    requested = targets if targets is not None else set(network.nodes)
    return {target: route_to(target) for target in requested}


def solve_query_document(
    network: Network,
    document: dict[str, Any],
) -> list[dict[str, Any]]:
    entries = document["queries"]
    groups: dict[str, list[int]] = {}
    for index, query in enumerate(entries):
        groups.setdefault(query["from"], []).append(index)

    results: list[dict[str, Any] | None] = [None] * len(entries)
    for source, indexes in groups.items():
        targets: set[str] = set()
        for index in indexes:
            query = entries[index]
            if query["type"] == "path":
                targets.add(query["to"])
            elif query["type"] == "table":
                targets.update(query["targets"])
            else:
                raise ValueError(f"unknown query type: {query['type']}")

        routes = shortest_from(network, source, targets)
        for index in indexes:
            query = entries[index]
            if query["type"] == "path":
                cost, path = routes[query["to"]]
                results[index] = {
                    "query_id": query["id"],
                    "type": "path",
                    "from": source,
                    "to": query["to"],
                    "cost": cost,
                    "path": path,
                }
            else:
                rows = []
                for target in query["targets"]:
                    cost, path = routes[target]
                    rows.append({"to": target, "cost": cost, "path": path})
                results[index] = {
                    "query_id": query["id"],
                    "type": "table",
                    "from": source,
                    "rows": rows,
                }

    return [result for result in results if result is not None]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} <query-file>", file=sys.stderr)
        return 2

    try:
        query_path = Path(argv[1])
        query_document = load_json(query_path)
        network_path = resolve_network_path(query_path, query_document["network"])
        network = Network(load_json(network_path))
        results = solve_query_document(network, query_document)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    json.dump(results, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
