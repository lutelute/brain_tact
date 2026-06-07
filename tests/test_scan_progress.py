"""compute_progress(差分検出)のテスト。"""

from brain_tact.scan import compute_progress


def test_first_sighting_is_changed():
    p = compute_progress("abc", 1000.0, None)
    assert p == {"changed": True, "stagnant_cycles": 0}


def test_screen_change_resets_stagnation():
    prev = {"screen_hash": "old", "jsonl_mtime": 1000.0,
            "progress": {"changed": False, "stagnant_cycles": 3}}
    p = compute_progress("new", 1000.0, prev)
    assert p == {"changed": True, "stagnant_cycles": 0}


def test_jsonl_advance_counts_as_change():
    """画面が同じでもjsonlが進んでいれば変化(裏でツールが動いている)。"""
    prev = {"screen_hash": "same", "jsonl_mtime": 1000.0,
            "progress": {"changed": False, "stagnant_cycles": 1}}
    p = compute_progress("same", 1100.0, prev)
    assert p["changed"] is True


def test_stagnation_accumulates():
    prev = {"screen_hash": "same", "jsonl_mtime": 1000.0,
            "progress": {"changed": True, "stagnant_cycles": 0}}
    p1 = compute_progress("same", 1000.0, prev)
    assert p1 == {"changed": False, "stagnant_cycles": 1}
    prev2 = {"screen_hash": "same", "jsonl_mtime": 1000.0, "progress": p1}
    p2 = compute_progress("same", 1000.0, prev2)
    assert p2 == {"changed": False, "stagnant_cycles": 2}


def test_small_mtime_jitter_ignored():
    """1秒未満のmtime揺れは進行とみなさない。"""
    prev = {"screen_hash": "same", "jsonl_mtime": 1000.0,
            "progress": {"changed": False, "stagnant_cycles": 0}}
    p = compute_progress("same", 1000.5, prev)
    assert p["changed"] is False


def test_missing_jsonl_safe():
    prev = {"screen_hash": "same", "jsonl_mtime": None,
            "progress": {"changed": False, "stagnant_cycles": 0}}
    p = compute_progress("same", None, prev)
    assert p == {"changed": False, "stagnant_cycles": 1}
