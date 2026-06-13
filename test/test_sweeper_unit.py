import json

import pytest

from alphaex.sweeper import Sweeper

CFG_PATH = "test/cfg/variables.json"


@pytest.fixture
def sweeper():
    return Sweeper(CFG_PATH)


def _write_cfg(tmp_path, cfg_dict):
    path = tmp_path / "variables.json"
    path.write_text(json.dumps(cfg_dict))
    return str(path)


def test_total_combinations_matches_fixture(sweeper):
    assert sweeper.total_combinations == 33


def test_keys_set_contains_all_sweep_variables(sweeper):
    assert sweeper.keys_set == {
        "algorithm",
        "param1",
        "param2",
        "param3",
        "param4",
        "param5",
        "param6",
        "simulator",
    }


@pytest.mark.parametrize(
    "idx,expected",
    [
        (
            0,
            {
                "run": 0,
                "simulator": "simulator_1",
                "algorithm": "algorithm_1",
                "param1": "param1_1",
                "param2": 0.1,
                "param3": 1,
            },
        ),
        (
            1,
            {
                "run": 0,
                "simulator": "simulator_1",
                "algorithm": "algorithm_1",
                "param1": "param1_2",
                "param2": 0.1,
                "param3": 1,
            },
        ),
        (
            7,
            {
                "run": 0,
                "simulator": "simulator_1",
                "algorithm": "algorithm_1",
                "param1": "param1_4",
                "param2": 0.4,
                "param3": 1,
            },
        ),
        (
            8,
            {
                "run": 0,
                "simulator": "simulator_1",
                "algorithm": "algorithm_1",
                "param1": "param1_1",
                "param2": 0.1,
                "param3": 2,
            },
        ),
        (
            23,
            {
                "run": 0,
                "simulator": "simulator_1",
                "algorithm": "algorithm_1",
                "param1": "param1_4",
                "param2": 0.4,
                "param3": 3,
            },
        ),
        (
            24,
            {
                "run": 0,
                "simulator": "simulator_1",
                "algorithm": "algorithm_2",
                "param1": "param1_3",
                "param4": True,
            },
        ),
        (
            27,
            {
                "run": 0,
                "simulator": "simulator_1",
                "algorithm": "algorithm_2",
                "param1": "param1_4",
                "param4": False,
            },
        ),
        (
            28,
            {
                "run": 0,
                "simulator": "simulator_2",
                "algorithm": "algorithm_2",
                "param1": "param1_3",
                "param4": True,
            },
        ),
        (
            32,
            {
                "run": 0,
                "simulator": "simulator_2",
                "algorithm": "algorithm_3",
                "param5": "param5_1",
                "param6": True,
            },
        ),
    ],
)
def test_parse_returns_expected_dict(sweeper, idx, expected):
    assert sweeper.parse(idx) == expected


def test_parse_does_not_leak_num_combinations_key(sweeper):
    for idx in (0, 17, 28, 32):
        assert "num_combinations" not in sweeper.parse(idx)


def test_parse_run_increments_every_total_combinations(sweeper):
    base = sweeper.parse(0)
    next_run = sweeper.parse(sweeper.total_combinations)
    assert next_run["run"] == base["run"] + 1
    for key, value in base.items():
        if key == "run":
            continue
        assert next_run[key] == value


def test_parse_last_idx_has_max_run(sweeper):
    num_runs = 10
    last_idx = sweeper.total_combinations * num_runs - 1
    assert sweeper.parse(last_idx)["run"] == num_runs - 1


def test_search_filters_by_known_keys(sweeper):
    results = sweeper.search({"param1": "param1_3", "param4": True}, 3)
    assert len(results) == 2
    assert {r["simulator"] for r in results} == {"simulator_1", "simulator_2"}
    for r in results:
        assert r["algorithm"] == "algorithm_2"
        assert r["param1"] == "param1_3"
        assert r["param4"] is True
        assert len(r["ids"]) == 3


def test_search_ids_stride_equals_total_combinations(sweeper):
    results = sweeper.search({"algorithm": "algorithm_3"}, 4)
    assert len(results) == 1
    expected_ids = [32 + run * sweeper.total_combinations for run in range(4)]
    assert results[0]["ids"] == expected_ids


def test_search_ignores_unknown_keys(sweeper):
    # README documents this: keys not present in self.config_dict are dropped.
    unknown_only = sweeper.search({"unknown_key": "x"}, 2)
    empty_search = sweeper.search({}, 2)
    assert unknown_only == empty_search
    # And one of each per total_combinations.
    assert len(unknown_only) == sweeper.total_combinations


def test_search_mixes_known_and_unknown_keys(sweeper):
    mixed = sweeper.search({"algorithm": "algorithm_3", "totally_unknown": 0}, 1)
    only_known = sweeper.search({"algorithm": "algorithm_3"}, 1)
    assert mixed == only_known


def test_search_returns_empty_for_impossible_value(sweeper):
    assert sweeper.search({"param1": "DOES_NOT_EXIST"}, 1) == []


def test_get_num_combinations_leaf_list():
    assert Sweeper.get_num_combinations([1, 2, 3]) == 3


def test_get_num_combinations_with_dict_values():
    values = [
        {"num_combinations": 4},
        {"num_combinations": 8},
        "leaf",
    ]
    assert Sweeper.get_num_combinations(values) == 13


def test_get_value_and_relative_idx_leaf_first():
    value, rel = Sweeper.get_value_and_relative_idx(["a", "b", "c"], 0)
    assert value == "a"
    assert rel == 0


def test_get_value_and_relative_idx_leaf_last():
    value, rel = Sweeper.get_value_and_relative_idx(["a", "b", "c"], 2)
    assert value == "c"
    assert rel == 0


def test_get_value_and_relative_idx_with_dict_value():
    values = [
        {"num_combinations": 3, "label": "first"},
        {"num_combinations": 2, "label": "second"},
    ]
    value, rel = Sweeper.get_value_and_relative_idx(values, 3)
    assert value["label"] == "second"
    assert rel == 0


def test_get_value_and_relative_idx_raises_when_idx_out_of_range():
    # Pre-fix: the fallback returned a bare int, so callers' tuple unpack would
    # explode with a misleading "cannot unpack non-iterable int" one frame up.
    # Post-fix: raise IndexError at the source with a useful message (issue #22).
    with pytest.raises(IndexError, match="idx 99"):
        Sweeper.get_value_and_relative_idx(["a", "b", "c"], 99)


def test_get_value_and_relative_idx_raises_at_exact_boundary():
    # idx == len(values) is the smallest out-of-range value for a leaf list.
    with pytest.raises(IndexError):
        Sweeper.get_value_and_relative_idx(["a", "b", "c"], 3)


def test_minimal_single_value_sweep_runs_increment(tmp_path):
    cfg_path = _write_cfg(tmp_path, {"alpha": ["only"]})
    s = Sweeper(cfg_path)
    assert s.total_combinations == 1
    assert s.parse(0) == {"run": 0, "alpha": "only"}
    assert s.parse(5) == {"run": 5, "alpha": "only"}


def test_two_independent_dims_first_key_cycles_fastest(tmp_path):
    cfg_path = _write_cfg(tmp_path, {"x": [1, 2], "y": ["a", "b", "c"]})
    s = Sweeper(cfg_path)
    assert s.total_combinations == 6
    assert s.parse(0) == {"run": 0, "x": 1, "y": "a"}
    assert s.parse(1) == {"run": 0, "x": 2, "y": "a"}
    assert s.parse(2) == {"run": 0, "x": 1, "y": "b"}
    assert s.parse(5) == {"run": 0, "x": 2, "y": "c"}
