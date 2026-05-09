from __future__ import annotations

GUARD_WRONG_ANSWER_KEY = "guard.wrong_answer_triggered"
MEMORY_FILTER_DECISION_PREFIX = "memory_filter."


class MemoryMetrics:
    @staticmethod
    def _repo():
        from memory.service import memory_service

        return memory_service.repo

    @staticmethod
    def _safe_increment(*, scope: str, metric_key: str, delta: int = 1) -> None:
        try:
            MemoryMetrics._repo().increment_short_runtime_metric(
                memory_scope=scope,
                metric_key=metric_key,
                delta=delta,
            )
        except Exception:
            return

    def record_wrong_answer_guard_trigger(self, *, memory_scope: str) -> None:
        scope = (memory_scope or "global").strip() or "global"
        self._safe_increment(scope=scope, metric_key=GUARD_WRONG_ANSWER_KEY)

    def record_scope_resolution(
        self,
        *,
        resolved_scope: str,
        source: str,
        source_key: str,
    ) -> None:
        scope = (resolved_scope or "global").strip() or "global"
        normalized_source = (source or "default").strip().lower() or "default"
        normalized_key = (source_key or "").strip().lower()
        self._safe_increment(
            scope=scope,
            metric_key=f"scope_resolution.source.{normalized_source}",
        )
        try:
            self._repo().create_short_scope_resolution_event(
                memory_scope=scope,
                source=normalized_source,
                source_key=normalized_key,
            )
        except Exception:
            return

    def get_scope_snapshot(self, *, memory_scope: str) -> dict:
        scope = (memory_scope or "global").strip() or "global"
        source_metric_rows = self._repo().get_short_runtime_metric_counts(
            memory_scope=scope,
            prefix="scope_resolution.source.",
        )
        source_counts: dict[str, int] = {}
        for key, value in source_metric_rows.items():
            source_name = key.replace("scope_resolution.source.", "", 1).strip()
            if source_name:
                source_counts[source_name] = int(value)
        recent = self._repo().list_short_scope_resolution_events(
            memory_scope=scope,
            limit=20,
        )
        return {
            "scope": scope,
            "source_counts": source_counts,
            "recent_resolutions": recent,
        }

    def get_wrong_answer_guard_triggers(self, *, memory_scope: str) -> int:
        scope = (memory_scope or "global").strip() or "global"
        rows = self._repo().get_short_runtime_metric_counts(
            memory_scope=scope,
            prefix=GUARD_WRONG_ANSWER_KEY,
        )
        return int(rows.get(GUARD_WRONG_ANSWER_KEY, 0))

    def record_retrieval_source_blend(
        self,
        *,
        memory_scope: str,
        source_counts: dict[str, int],
        top_source: str,
    ) -> None:
        scope = (memory_scope or "global").strip() or "global"
        normalized_top = (top_source or "none").strip().lower() or "none"
        for key, value in (source_counts or {}).items():
            normalized_key = (str(key) or "").strip().lower()
            if not normalized_key:
                continue
            self._safe_increment(
                scope=scope,
                metric_key=f"retrieval_blend.source.{normalized_key}",
                delta=max(0, int(value or 0)),
            )
        self._safe_increment(
            scope=scope,
            metric_key=f"retrieval_blend.top_source.{normalized_top}",
            delta=1,
        )

    def get_retrieval_source_blend_snapshot(self, *, memory_scope: str) -> dict:
        scope = (memory_scope or "global").strip() or "global"
        metric_rows = self._repo().get_short_runtime_metric_counts(
            memory_scope=scope,
            prefix="retrieval_blend.",
        )
        source_counts: dict[str, int] = {}
        top_source_counts: dict[str, int] = {}
        for key, value in metric_rows.items():
            if key.startswith("retrieval_blend.source."):
                source_name = key.replace("retrieval_blend.source.", "", 1).strip()
                if source_name:
                    source_counts[source_name] = int(value)
            elif key.startswith("retrieval_blend.top_source."):
                source_name = key.replace("retrieval_blend.top_source.", "", 1).strip()
                if source_name:
                    top_source_counts[source_name] = int(value)
        return {
            "scope": scope,
            "source_counts": source_counts,
            "top_source_counts": top_source_counts,
        }

    def record_shadow_comparison(
        self,
        *,
        memory_scope: str,
        prod_items: list[dict],
        shadow_items: list[dict],
    ) -> None:
        scope = (memory_scope or "global").strip() or "global"
        self._safe_increment(scope=scope, metric_key="shadow.total", delta=1)
        prod_count = len(prod_items or [])
        shadow_count = len(shadow_items or [])
        if prod_count <= 0 and shadow_count > 0:
            self._safe_increment(scope=scope, metric_key="shadow.prod_empty_shadow_nonempty", delta=1)
        if shadow_count <= 0 and prod_count > 0:
            self._safe_increment(scope=scope, metric_key="shadow.shadow_empty_prod_nonempty", delta=1)
        prod_top = str((prod_items or [{}])[0].get("text") or "").strip().lower() if prod_count > 0 else ""
        shadow_top = str((shadow_items or [{}])[0].get("text") or "").strip().lower() if shadow_count > 0 else ""
        if prod_top and shadow_top:
            if prod_top == shadow_top:
                self._safe_increment(scope=scope, metric_key="shadow.top_match", delta=1)
            else:
                self._safe_increment(scope=scope, metric_key="shadow.top_mismatch", delta=1)
        prod_max_score = max((float(item.get("score") or 0.0) for item in (prod_items or [])), default=0.0)
        if prod_count > 0 and prod_max_score < 0.5:
            self._safe_increment(scope=scope, metric_key="shadow.prod_low_confidence", delta=1)

    def get_shadow_snapshot(self, *, memory_scope: str) -> dict:
        scope = (memory_scope or "global").strip() or "global"
        rows = self._repo().get_short_runtime_metric_counts(
            memory_scope=scope,
            prefix="shadow.",
        )
        return {
            "scope": scope,
            "counters": rows,
        }

    def record_memory_filter_decision(self, *, memory_scope: str, decision: str) -> None:
        scope = (memory_scope or "global").strip() or "global"
        normalized = (decision or "unknown").strip().lower().replace(" ", "_")
        self._safe_increment(
            scope=scope,
            metric_key=f"{MEMORY_FILTER_DECISION_PREFIX}{normalized}",
            delta=1,
        )

    def get_memory_filter_snapshot(self, *, memory_scope: str) -> dict:
        scope = (memory_scope or "global").strip() or "global"
        rows = self._repo().get_short_runtime_metric_counts(
            memory_scope=scope,
            prefix=MEMORY_FILTER_DECISION_PREFIX,
        )
        return {
            "scope": scope,
            "decisions": rows,
        }


memory_metrics = MemoryMetrics()

