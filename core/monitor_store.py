"""
MacroX — Monitor Store v2
Schema:
  scenes: [ { id, name, hotkey, zones: [ {zone_data} ] } ]
  active_scene_id: int | null

Zone fields:
  id, name, active, priority (1=critical … 3=low),
  rect, reference (b64), condition, threshold,
  action_type ("key"|"macro"), action_key, action_macro_id,
  cooldown_ms, parallel (bool) — fire without queue
"""
import json, os, logging
log = logging.getLogger(__name__)

_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "config", "monitors.json"
)

PRIORITY_LABELS = {1: "Критический", 2: "Обычный", 3: "Фоновый"}
PRIORITY_COLORS = {1: "#E74C3C", 2: "#3D8EF0", 3: "#4A5068"}


class MonitorStore:
    def __init__(self):
        self._scenes:        list[dict] = []
        self._active_scene:  int | None = None
        self._next_scene_id  = 1
        self._next_zone_id   = 1
        self.load()

    # ── Persistence ────────────────────────────────────────────────────────
    def load(self):
        try:
            if os.path.exists(_PATH):
                with open(_PATH) as f:
                    raw = json.load(f)
                self._scenes       = raw.get("scenes", [])
                self._active_scene = raw.get("active_scene_id")
                all_sids = [s["id"] for s in self._scenes]
                all_zids = [z["id"] for s in self._scenes for z in s.get("zones", [])]
                all_gids = [g["id"] for s in self._scenes for g in s.get("groups", [])]
                self._next_scene_id = max(all_sids, default=0) + 1
                self._next_zone_id  = max(all_zids + all_gids, default=0) + 1
        except Exception as e:
            log.error(f"MonitorStore.load: {e}")

    def save(self):
        try:
            os.makedirs(os.path.dirname(_PATH), exist_ok=True)
            with open(_PATH, "w") as f:
                json.dump({
                    "scenes":          self._scenes,
                    "active_scene_id": self._active_scene,
                }, f, indent=2)
        except Exception as e:
            log.error(f"MonitorStore.save: {e}")

    # ── Scene CRUD ─────────────────────────────────────────────────────────
    def scenes(self) -> list[dict]:
        return list(self._scenes)

    def get_scene(self, sid: int) -> dict | None:
        for s in self._scenes:
            if s["id"] == sid: return s
        return None

    def add_scene(self, name: str, hotkey: str = "") -> int:
        sid = self._next_scene_id; self._next_scene_id += 1
        self._scenes.append({"id": sid, "name": name, "hotkey": hotkey, "zones": []})
        if self._active_scene is None:
            self._active_scene = sid
        self.save(); return sid

    def rename_scene(self, sid: int, name: str, hotkey: str = ""):
        s = self.get_scene(sid)
        if s: s["name"] = name; s["hotkey"] = hotkey; self.save()

    def delete_scene(self, sid: int):
        self._scenes = [s for s in self._scenes if s["id"] != sid]
        if self._active_scene == sid:
            self._active_scene = self._scenes[0]["id"] if self._scenes else None
        self.save()

    def set_active_scene(self, sid: int):
        self._active_scene = sid; self.save()

    def active_scene_id(self) -> int | None:
        return self._active_scene

    def active_scene(self) -> dict | None:
        if self._active_scene is None: return None
        return self.get_scene(self._active_scene)

    # ── Zone CRUD (within a scene) ─────────────────────────────────────────
    def zones_for(self, sid: int) -> list[dict]:
        s = self.get_scene(sid)
        return list(s["zones"]) if s else []

    def active_zones(self) -> list[dict]:
        """All zones in active scene, sorted by priority."""
        s = self.active_scene()
        if not s: return []
        return sorted(s.get("zones", []), key=lambda z: z.get("priority", 2))

    def add_zone(self, sid: int, zone: dict) -> int:
        s = self.get_scene(sid)
        if not s: return -1
        zone = dict(zone); zone["id"] = self._next_zone_id; self._next_zone_id += 1
        s["zones"].append(zone); self.save(); return zone["id"]

    def update_zone(self, sid: int, zid: int, data: dict):
        s = self.get_scene(sid)
        if not s: return
        for i, z in enumerate(s["zones"]):
            if z["id"] == zid:
                s["zones"][i] = {**z, **data, "id": zid}
                self.save(); return

    def delete_zone(self, sid: int, zid: int):
        s = self.get_scene(sid)
        if s:
            s["zones"] = [z for z in s["zones"] if z["id"] != zid]
            self.save()

    def get_zone(self, sid: int, zid: int) -> dict | None:
        for z in self.zones_for(sid): 
            if z["id"] == zid: return z
        return None

    def reorder_zones(self, sid: int, ordered_ids: list[int]):
        """Reorder zones within a scene by id list."""
        s = self.get_scene(sid)
        if not s: return
        idx = {z["id"]: z for z in s["zones"]}
        s["zones"] = [idx[zid] for zid in ordered_ids if zid in idx]
        self.save()

    # ── Condition Groups CRUD ─────────────────────────────────────────────
    def groups_for(self, sid: int) -> list[dict]:
        s = self.get_scene(sid)
        return list(s.get("groups", [])) if s else []

    def add_group(self, sid: int, group: dict) -> int:
        s = self.get_scene(sid)
        if not s:
            return -1
        group = dict(group)
        group["id"] = self._next_zone_id   # переиспользуем счётчик
        self._next_zone_id += 1
        s.setdefault("groups", []).append(group)
        self.save()
        return group["id"]

    def update_group(self, sid: int, gid: int, data: dict):
        s = self.get_scene(sid)
        if not s:
            return
        for i, g in enumerate(s.get("groups", [])):
            if g["id"] == gid:
                s["groups"][i] = {**g, **data, "id": gid}
                self.save()
                return

    def delete_group(self, sid: int, gid: int):
        s = self.get_scene(sid)
        if s:
            s["groups"] = [g for g in s.get("groups", []) if g["id"] != gid]
            self.save()

    def active_groups(self) -> list[dict]:
        """Все группы активной сцены."""
        s = self.active_scene()
        if not s:
            return []
        return [g for g in s.get("groups", []) if g.get("active", False)]

    # ── Flat fallback (for engine that just needs active zones) ────────────
    def all(self) -> list[dict]:
        """Backward-compat: returns active scene's zones."""
        return self.active_zones()


_store: MonitorStore | None = None
def get_monitor_store() -> MonitorStore:
    global _store
    if _store is None: _store = MonitorStore()
    return _store
