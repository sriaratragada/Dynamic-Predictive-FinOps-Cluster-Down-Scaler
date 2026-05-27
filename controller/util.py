"""
Shared helpers used across the controller package.

Kept deliberately tiny — anything more than a one-liner with no dependencies
on other controller modules belongs in its own file.
"""

# Node labels marking the cluster control plane.  Cordoning these is never
# safe regardless of utilisation, so both the controller and dashboard
# treat them as forbidden targets.
CONTROL_PLANE_LABELS = frozenset({
    "node-role.kubernetes.io/control-plane",
    "node-role.kubernetes.io/master",
})


def parse_cpu(cpu_str: str) -> float:
    """Convert a Kubernetes CPU quantity to fractional cores.

    Accepts both milli-CPU (``"500m"``) and whole-core (``"2"``) forms.
    Empty / unparseable input returns 0.0 — callers treat that as
    "node has no schedulable CPU".
    """
    if not cpu_str:
        return 0.0
    cpu_str = str(cpu_str)
    if cpu_str.endswith("m"):
        try:
            return int(cpu_str[:-1]) / 1000.0
        except ValueError:
            return 0.0
    try:
        return float(cpu_str)
    except ValueError:
        return 0.0


def is_control_plane(node) -> bool:
    """True when the node carries a control-plane role label.

    Works on both real ``V1Node`` objects and the duck-typed demo
    namespaces — both expose ``metadata.labels`` as a dict or None.
    """
    labels = (getattr(node.metadata, "labels", None) or {})
    return any(lbl in labels for lbl in CONTROL_PLANE_LABELS)
