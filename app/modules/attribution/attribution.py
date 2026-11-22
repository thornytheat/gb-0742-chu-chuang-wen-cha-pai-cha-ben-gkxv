from collections import defaultdict

from app.timebase import seconds, utc

# 责任归因结论：共同环境事件、单柜事件，或证据不足以判定（保留原段）。
COMMON = "COMMON_EVENT"
SINGLE = "SINGLE_CABINET"
INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
VERDICTS = (COMMON, SINGLE, INSUFFICIENT)


class _UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, node):
        self.parent.setdefault(node, node)
        root = node
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[node] != node:
            self.parent[node], node = root, self.parent[node]
        return root

    def union(self, left, right):
        self.parent[self.find(left)] = self.find(right)


def _episode_span(episode):
    return seconds(episode["start"]), seconds(episode["end"])


def _grade_index(grades):
    index = defaultdict(dict)
    for slot in grades:
        index[slot["cabinet"]][slot["hour"]] = slot
    return index


def attribute(spec, grades, episodes):
    """跨柜责任归因。

    同一时段多柜异常互相重叠时合并为共同环境事件；其余异常段须由相邻柜的
    稳定柜时反证为单柜事件。相邻柜在覆盖时窗内缺证（缺小时、缺证柜时）则
    证据不足，保留原段不下结论。
    """
    cabinet_ids = sorted(item.id for item in spec.cabinet_hours)
    lookup = _grade_index(grades)
    ordered = sorted(episodes, key=lambda item: (item["cabinet"], seconds(item["start"]), item["id"]))
    spans = {item["id"]: _episode_span(item) for item in ordered}

    # 按时间重叠把跨柜异常段并为同一事件（同柜段之间不连接）。
    groups = _UnionFind()
    for episode in ordered:
        groups.find(episode["id"])
    for i, left in enumerate(ordered):
        left_start, left_end = spans[left["id"]]
        for right in ordered[i + 1:]:
            if right["cabinet"] == left["cabinet"]:
                continue
            right_start, right_end = spans[right["id"]]
            if left_start < right_end and right_start < left_end:
                groups.union(left["id"], right["id"])

    members = defaultdict(list)
    for episode in ordered:
        members[groups.find(episode["id"])].append(episode)

    # 共同事件按起始时刻、柜号固定编号，保证重跑结论稳定。
    common_buckets = [bucket for bucket in members.values()
                      if len({item["cabinet"] for item in bucket}) >= 2]
    common_buckets.sort(key=lambda bucket: (min(spans[item["id"]][0] for item in bucket),
                                            sorted(item["cabinet"] for item in bucket)))
    event_ids, events = {}, []
    for index, bucket in enumerate(common_buckets, 1):
        event_id = f"ENV-E{index:02d}"
        for item in bucket:
            event_ids[item["id"]] = event_id
        events.append({"id": event_id,
                       "cabinets": sorted({item["cabinet"] for item in bucket}),
                       "start": utc(min(spans[item["id"]][0] for item in bucket)),
                       "end": utc(max(spans[item["id"]][1] for item in bucket)),
                       "episodes": sorted(item["id"] for item in bucket)})

    verdicts = []
    for episode in ordered:
        start, end = spans[episode["id"]]
        own_hours = set(range(start, end, 3600))
        shared, counter = [], []
        for other in members[groups.find(episode["id"])]:
            if other["cabinet"] == episode["cabinet"]:
                continue
            other_start, other_end = spans[other["id"]]
            for hour in sorted(hour for hour in own_hours if other_start <= hour < other_end):
                slot = lookup[other["cabinet"]].get(hour)
                shared.append({"cabinet": other["cabinet"], "hour": utc(hour),
                               "state": slot["state"] if slot else "MISSING",
                               "episode": other["id"],
                               "upper": slot["upper"] if slot else None,
                               "lower": slot["lower"] if slot else None})

        if shared:
            verdict = {"episode": episode["id"], "cabinet": episode["cabinet"],
                       "start": episode["start"], "end": episode["end"],
                       "hours": episode["hours"], "kind": episode["kind"],
                       "verdict": COMMON, "event": event_ids[episode["id"]], "retained": False,
                       "shared_evidence": sorted(shared, key=lambda item: (item["cabinet"], item["hour"])),
                       "counter_evidence": [], "gaps": []}
        else:
            # 单柜事件需要每个异常小时都有相邻柜的稳定柜时反证；
            # 班次只有一个柜时无柜可对照，同样按证据不足保留。
            unresolved = len(cabinet_ids) < 2
            for cabinet in cabinet_ids:
                if cabinet == episode["cabinet"]:
                    continue
                for hour in sorted(own_hours):
                    slot = lookup[cabinet].get(hour)
                    state = slot["state"] if slot else "MISSING"
                    if state != "STABLE":
                        unresolved = True
                    counter.append({"cabinet": cabinet, "hour": utc(hour), "state": state,
                                    "upper": slot["upper"] if slot else None,
                                    "lower": slot["lower"] if slot else None})
            gaps = sorted((item["cabinet"], item["hour"]) for item in counter if item["state"] != "STABLE")
            verdict = {"episode": episode["id"], "cabinet": episode["cabinet"],
                       "start": episode["start"], "end": episode["end"],
                       "hours": episode["hours"], "kind": episode["kind"],
                       "verdict": INSUFFICIENT if unresolved else SINGLE,
                       "event": None, "retained": unresolved,
                       "shared_evidence": [],
                       "counter_evidence": sorted(counter, key=lambda item: (item["cabinet"], item["hour"])),
                       "gaps": [{"cabinet": cabinet, "hour": hour} for cabinet, hour in gaps]}
        verdicts.append(verdict)

    counts = {name: sum(item["verdict"] == name for item in verdicts) for name in VERDICTS}
    return {"events": events, "verdicts": verdicts, "counts": counts,
            "retained": [item["episode"] for item in verdicts if item["retained"]]}
