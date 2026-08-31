from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .model import (
    ContextSet,
    MetaCandidate,
    MetaDecision,
    Node,
    NodeType,
    PermissionCandidate,
    PermissionDecision,
    PermissionSnapshot,
    SubjectRef,
    SubjectType,
)
from .validation import normalize_meta_key, normalize_permission


@dataclass(frozen=True, slots=True)
class _InheritedSubject:
    subject: SubjectRef
    distance: int
    group_weight: int


class PermissionResolver:
    def resolve(
        self,
        snapshot: PermissionSnapshot,
        permission: str,
        contexts: ContextSet | None = None,
        *,
        now: int,
    ) -> PermissionDecision:
        requested = normalize_permission(permission)
        active_contexts = contexts or ContextSet()
        candidates: list[PermissionCandidate] = []

        for inherited in self._subjects(snapshot, active_contexts, now):
            for node in snapshot.nodes.get(inherited.subject, ()):
                if node.type is not NodeType.PERMISSION:
                    continue
                if not node.active_at(now) or not node.contexts.matches(active_contexts):
                    continue
                specificity = self._permission_match_specificity(node.key, requested)
                if specificity < 0:
                    continue
                candidates.append(
                    PermissionCandidate(
                        node=node,
                        origin=inherited.subject,
                        direct=inherited.subject == snapshot.user,
                        inheritance_distance=inherited.distance,
                        group_weight=inherited.group_weight,
                        match_specificity=specificity,
                    )
                )

        ordered = tuple(sorted(candidates, key=self._candidate_priority, reverse=True))
        selected = ordered[0] if ordered else None
        return PermissionDecision(
            permission=requested,
            value=selected.node.permission_value if selected else None,
            selected=selected,
            candidates=ordered,
        )

    def effective_groups(
        self,
        snapshot: PermissionSnapshot,
        contexts: ContextSet | None = None,
        *,
        now: int,
    ) -> tuple[str, ...]:
        inherited = self._subjects(snapshot, contexts or ContextSet(), now)
        return tuple(item.subject.identifier for item in inherited if item.subject.type is SubjectType.GROUP)

    def primary_group(
        self,
        snapshot: PermissionSnapshot,
        contexts: ContextSet | None = None,
        *,
        now: int,
    ) -> str:
        groups = self.effective_groups(snapshot, contexts, now=now)
        return max(
            groups,
            key=lambda name: (snapshot.groups.get(name).weight if name in snapshot.groups else 0, name),
            default=snapshot.default_group,
        )

    def resolve_meta(
        self,
        snapshot: PermissionSnapshot,
        key: str,
        contexts: ContextSet | None = None,
        *,
        now: int,
    ) -> MetaDecision:
        return self._resolve_meta_node(
            snapshot,
            NodeType.META,
            normalize_meta_key(key),
            contexts or ContextSet(),
            now,
        )

    def resolve_prefix(
        self,
        snapshot: PermissionSnapshot,
        contexts: ContextSet | None = None,
        *,
        now: int,
    ) -> MetaDecision:
        return self._resolve_meta_node(
            snapshot,
            NodeType.PREFIX,
            NodeType.PREFIX.value,
            contexts or ContextSet(),
            now,
        )

    def resolve_suffix(
        self,
        snapshot: PermissionSnapshot,
        contexts: ContextSet | None = None,
        *,
        now: int,
    ) -> MetaDecision:
        return self._resolve_meta_node(
            snapshot,
            NodeType.SUFFIX,
            NodeType.SUFFIX.value,
            contexts or ContextSet(),
            now,
        )

    def resolve_meta_map(
        self,
        snapshot: PermissionSnapshot,
        contexts: ContextSet | None = None,
        *,
        now: int,
    ) -> dict[str, str]:
        active_contexts = contexts or ContextSet()
        subjects = self._subjects(snapshot, active_contexts, now)
        keys = sorted(
            {
                node.key
                for inherited in subjects
                for node in snapshot.nodes.get(inherited.subject, ())
                if node.type is NodeType.META
                and node.active_at(now)
                and node.contexts.matches(active_contexts)
            }
        )
        values: dict[str, str] = {}
        for key in keys:
            decision = self._resolve_meta_node(
                snapshot,
                NodeType.META,
                key,
                active_contexts,
                now,
            )
            if decision.value is not None:
                values[key] = decision.value
        return values

    def _resolve_meta_node(
        self,
        snapshot: PermissionSnapshot,
        node_type: NodeType,
        key: str,
        contexts: ContextSet,
        now: int,
    ) -> MetaDecision:
        if node_type not in {NodeType.META, NodeType.PREFIX, NodeType.SUFFIX}:
            raise ValueError(f"Unsupported metadata node type: {node_type.value}")
        candidates: list[MetaCandidate] = []
        for inherited in self._subjects(snapshot, contexts, now):
            for node in snapshot.nodes.get(inherited.subject, ()):
                if node.type is not node_type or node.key != key:
                    continue
                if not node.active_at(now) or not node.contexts.matches(contexts):
                    continue
                candidates.append(
                    MetaCandidate(
                        node=node,
                        origin=inherited.subject,
                        direct=inherited.subject == snapshot.user,
                        inheritance_distance=inherited.distance,
                        group_weight=inherited.group_weight,
                    )
                )
        ordered = tuple(
            sorted(
                candidates,
                key=lambda candidate: self._meta_candidate_priority(candidate, node_type),
                reverse=True,
            )
        )
        selected = ordered[0] if ordered else None
        return MetaDecision(
            type=node_type,
            key=key,
            value=selected.node.value if selected else None,
            selected=selected,
            candidates=ordered,
        )

    def _subjects(
        self,
        snapshot: PermissionSnapshot,
        contexts: ContextSet,
        now: int,
    ) -> tuple[_InheritedSubject, ...]:
        result: list[_InheritedSubject] = [_InheritedSubject(snapshot.user, 0, 2**31 - 1)]
        roots: list[str] = [snapshot.default_group]
        roots.extend(self._active_parents(snapshot.nodes.get(snapshot.user, ()), contexts, now))
        roots = sorted(
            set(roots),
            key=lambda name: (snapshot.groups.get(name).weight if name in snapshot.groups else 0, name),
            reverse=True,
        )

        best: dict[str, tuple[int, int]] = {}
        queue: list[tuple[str, int, int, frozenset[str]]] = []
        for group_name in roots:
            weight = snapshot.groups.get(group_name).weight if group_name in snapshot.groups else 0
            queue.append((group_name, 1, weight, frozenset()))

        while queue:
            group_name, distance, root_weight, ancestry = queue.pop(0)
            if group_name in ancestry or group_name not in snapshot.groups:
                continue
            precedence = (root_weight, -distance)
            if group_name in best and best[group_name] >= precedence:
                continue
            best[group_name] = precedence
            subject = SubjectRef.group(group_name)
            next_ancestry = ancestry | {group_name}
            for parent in self._active_parents(snapshot.nodes.get(subject, ()), contexts, now):
                queue.append((parent, distance + 1, root_weight, next_ancestry))

        for group_name, (_root_weight, negative_distance) in sorted(
            best.items(), key=lambda item: (item[1][0], item[1][1], item[0]), reverse=True
        ):
            result.append(
                _InheritedSubject(
                    SubjectRef.group(group_name),
                    -negative_distance,
                    snapshot.groups[group_name].weight,
                )
            )
        return tuple(result)

    @staticmethod
    def _active_parents(nodes: Iterable[Node], contexts: ContextSet, now: int) -> tuple[str, ...]:
        return tuple(
            node.key
            for node in nodes
            if node.type is NodeType.PARENT
            and node.active_at(now)
            and node.contexts.matches(contexts)
        )

    @staticmethod
    def _permission_match_specificity(granted: str, requested: str) -> int:
        if granted == requested:
            return 1_000_000 + len(granted)
        if granted == "*":
            return 0
        if granted.endswith(".*") and requested.startswith(granted[:-1]):
            return len(granted) - 1
        return -1

    @staticmethod
    def _candidate_priority(candidate: PermissionCandidate) -> tuple[int, int, int, int, int, int, int, int]:
        node = candidate.node
        temporary_expiry_priority = -node.expires_at if node.expires_at is not None else -(2**63 - 1)
        return (
            int(candidate.direct),
            int(node.temporary),
            candidate.match_specificity,
            node.contexts.specificity,
            candidate.group_weight,
            -candidate.inheritance_distance,
            temporary_expiry_priority,
            int(not node.permission_value),
        )

    @staticmethod
    def _meta_candidate_priority(
        candidate: MetaCandidate,
        node_type: NodeType,
    ) -> tuple[int, int, int, int, int, int, int, int, int]:
        node = candidate.node
        temporary_expiry_priority = -node.expires_at if node.expires_at is not None else -(2**63 - 1)
        stack_priority = node.priority if node_type in {NodeType.PREFIX, NodeType.SUFFIX} else 0
        return (
            stack_priority,
            int(candidate.direct),
            int(node.temporary),
            node.contexts.specificity,
            candidate.group_weight,
            -candidate.inheritance_distance,
            temporary_expiry_priority,
            node.created_at,
            node.id or 0,
        )
