"""Blind review packets and explicit human labels for real-agent evidence."""
from __future__ import annotations

import json
import hashlib
from collections import defaultdict
from pathlib import Path

from core.artifacts import write_json
from report.detection import Observation


def review_id(sample_id):
    return "sample-" + hashlib.sha256(sample_id.encode()).hexdigest()[:20]


def export_review_packet(observations, output):
    """Hide detector conclusions and mutation labels; retain behavioral evidence."""
    samples = []
    for observation in observations:
        data = json.loads(Path(observation.evidence_path).read_text(encoding="utf-8-sig"))
        if "result" in data:
            attempt = data["result"]["attempts"][0]
            patch, trace = attempt["patch"], attempt["trace"]
        else:
            patch, trace = data.get("patch", {}), data.get("trace", {})
        trace = {k: v for k, v in trace.items() if k != "anomalies"}
        if "agent" in trace and trace["agent"].startswith(("eval:", "scripted:")):
            trace["agent"] = "scripted"
        patch = {k: v for k, v in patch.items() if k != "source"}
        samples.append({"sample_id": review_id(observation.sample_id),
                        "task": data.get("provenance", {}).get("task", {}),
                        "patch": patch, "trace": trace,
                        "needs_review": None, "functional_correct": None,
                        "reason": "", "reviewer": ""})
    return write_json(output, {"schema_version": 1, "instructions":
        "Review independently without detector results. Label needs_review (boolean), functional_correct (boolean/null), reason and reviewer. Do not infer malicious intent.",
        "samples": samples})


def apply_annotations(observations, annotation_paths, adjudication_path=None):
    """Require independent agreeing reviews or an explicit adjudication."""
    reviews = defaultdict(dict)
    known = {o.sample_id for o in observations}
    aliases = {review_id(sid): sid for sid in known}
    for path in annotation_paths:
        for item in json.loads(Path(path).read_text(encoding="utf-8-sig"))["samples"]:
            sid, reviewer = item["sample_id"], item.get("reviewer", "").strip()
            sid = aliases.get(sid, sid)
            if sid not in known:
                raise ValueError(f"Unknown sample id: {sid}")
            if type(item.get("needs_review")) is not bool or not reviewer or not item.get("reason", "").strip():
                raise ValueError(f"Incomplete human label for {sid}")
            if reviewer in reviews[sid]:
                raise ValueError(f"Duplicate reviewer {reviewer} for {sid}")
            reviews[sid][reviewer] = item
    adjudications = {}
    if adjudication_path:
        for item in json.loads(Path(adjudication_path).read_text(encoding="utf-8-sig"))["samples"]:
            if type(item.get("needs_review")) is not bool or not item.get("reviewer") or not item.get("reason"):
                raise ValueError("Adjudications require a label, reviewer and reason")
            sid = aliases.get(item['sample_id'], item['sample_id'])
            if sid not in known or sid in adjudications:
                raise ValueError('Unknown or duplicate adjudication sample')
            if item['reviewer'] in reviews[sid]:
                raise ValueError('Adjudicator must differ from the original reviewers')
            adjudications[sid] = item
    output = []
    for obs in observations:
        item = Observation(**obs.to_dict())
        labels = list(reviews[obs.sample_id].values())
        votes = {x["needs_review"] for x in labels}
        item.label = None
        item.labels = {"reviews": labels, "agreement": len(votes) == 1 and len(labels) >= 2}
        if len(labels) >= 2 and len(votes) == 1:
            item.label = int(next(iter(votes)))
        elif obs.sample_id in adjudications:
            decision = adjudications[obs.sample_id]
            if len(labels) < 2:
                raise ValueError("Adjudication requires at least two original reviews")
            item.label = int(decision["needs_review"])
            item.labels["adjudication"] = decision
        item.source = "human_labelled_agent" if item.label is not None and obs.source != "synthetic" else obs.source
        output.append(item)
    return output
