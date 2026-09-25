#!/usr/bin/env python3
"""turnwise: 带转向限制的最短路径求解器。

用法: python solve.py <查询文件>
从查询文件读入一批查询, 把结果 JSON 数组写到 stdout, 诊断走 stderr。
仅使用 Python 标准库。

口径(README 第 2、3 节):
- 状态是「刚驶入的那条边」而不是节点, 禁转作用在相邻两条边的接缝上;
- 合法路径先取代价最小者, 代价并列时按边 id 序列做字符串字典序比较,
  第一处不同处小者胜, 一方是另一方前缀时短者胜;
- 起点等于终点时答案为代价 0 的空路径。
"""

import heapq
import json
import os
import sys
from collections import OrderedDict

# 同一进程内, 起点相同的搜索结果会被缓存复用(超出上限按 LRU 淘汰),
# 同一来源的一批查询不必每次都全图重算。
_SOURCE_CACHE_SIZE = 16


class EdgeStateGraph:
    """把路网展开成「边状态」图: 状态是有向边, 转弯是状态之间的转移。"""

    def __init__(self, data):
        self.network_id = data.get("id", "")
        self.node_ids = {n["id"] for n in data["nodes"]}
        edges = data["edges"]
        self.edge_id = [e["id"] for e in edges]
        self.frm = [e["from"] for e in edges]
        self.to = [e["to"] for e in edges]
        self.cost = [e["cost"] for e in edges]
        self.edge_count = len(edges)
        self.out_edges = {n: [] for n in self.node_ids}
        self.in_edges = {n: [] for n in self.node_ids}
        for i, e in enumerate(edges):
            self.out_edges[e["from"]].append(i)
            self.in_edges[e["to"]].append(i)
        # sort outgoing edges by id so heap order is deterministic
        for ends in self.out_edges.values():
            ends.sort(key=self.edge_id.__getitem__)
        edge_index = {}
        for i, eid in enumerate(self.edge_id):
            edge_index[eid] = i
        m = self.edge_count
        self.restricted = set()
        for r in data.get("turn_restrictions", []):
            a = edge_index[r["in"]]
            b = edge_index[r["out"]]
            self.restricted.add(a * m + b)

    def dijkstra(self, source):
        """Run Dijkstra over edge states from the given start node.

        Heap entries are (cost, edge-id tuple, edge index).  When costs
        tie, the tuple comparison is exactly the README section 2 rule
        (string-wise lexicographic, shorter prefix wins), so the first
        time a state is popped it carries its best (cost, path) pair.
        """
        edge_id = self.edge_id
        to = self.to
        cost = self.cost
        out_edges = self.out_edges
        restricted = self.restricted
        m = self.edge_count
        dist_cost = [None] * m
        dist_path = [None] * m
        heap = []
        push = heapq.heappush
        for e in out_edges.get(source, ()):
            t = (edge_id[e],)
            dist_cost[e] = cost[e]
            dist_path[e] = t
            push(heap, (cost[e], t, e))
        while heap:
            d, p, e = heapq.heappop(heap)
            if dist_cost[e] != d or dist_path[e] != p:
                continue
            junction = to[e]
            for f in out_edges[junction]:
                if (e * m + f) in restricted:
                    continue
                nd = d + cost[f]
                npth = p + (edge_id[f], the the)
                dc = dist_cost[f]
