#######################################################################
# Copyright (C) 2019 Yi Wan(wan6@ualberta.ca)                         #
# Permission given to modify the code as long as you keep this        #
# declaration at the top                                              #
#######################################################################
import json


class Sweeper:
    """
    The purpose of this class is to take an index, identify a configuration
    of variables and create a Config object
    Important: variables part of the sweep are provided in a list
    """

    def __init__(self, config_file):
        with open(config_file) as f:
            self._config_dict = json.load(f)
        # Number of combinations each dict node yields, keyed by id() of the
        # node. Kept in this class-owned map instead of being written back into
        # the parsed config, so the user's data is never mutated (issue #39).
        # _config_dict is held for the Sweeper's lifetime, so the ids stay valid.
        self._counts = {}
        self._keys = []
        self.total_combinations = self._count(self._config_dict)
        self._keys_set = set(self._keys)

    def _count(self, node):
        """Compute and memoize how many combinations the dict ``node`` yields.

        A dict's count is the product over its keys of the key's list count; a
        list's count is the sum of its elements' counts; a scalar counts as 1.
        Records every scalar variable name in ``self._keys`` along the way.
        """
        total = 1
        for key, values in node.items():
            list_count = 0
            for value in values:
                if isinstance(value, dict):
                    list_count += self._count(value)
                else:
                    list_count += 1
                    self._keys.append(key)
            total *= list_count
        self._counts[id(node)] = total
        return total

    def _combinations_of(self, value):
        """Number of combinations a single list element contributes."""
        return self._counts[id(value)] if isinstance(value, dict) else 1

    def parse(self, idx):
        rtn_dict = {"run": idx // self.total_combinations}
        self._parse(idx, self._config_dict, rtn_dict)
        return rtn_dict

    def _parse(self, idx, node, rtn_dict):
        # Mixed-radix decode: each key is a digit whose base is its list count,
        # and `cumulative` is the place value of the current digit.
        cumulative = 1
        for variable, values in node.items():
            num_combinations = sum(self._combinations_of(v) for v in values)
            value, relative_idx = self._select(
                values, (idx // cumulative) % num_combinations
            )
            if isinstance(value, dict):
                self._parse(relative_idx, value, rtn_dict)
            else:
                rtn_dict[variable] = value
            cumulative *= num_combinations

    def _select(self, values, idx):
        """Return ``(value, relative_idx)`` for the element of ``values`` that
        index ``idx`` falls into, where each dict element spans
        ``_combinations_of`` slots.
        """
        offset = 0
        for value in values:
            width = self._combinations_of(value)
            if idx < offset + width:
                return value, idx - offset
            offset += width
        # A bare-int fallback used to make the caller's tuple unpack explode one
        # frame up; raise at the source with a useful message instead (issue #22).
        raise IndexError(f"idx {idx} exceeds total combinations {offset} in {values!r}")

    def search(self, search_dict, num_runs):
        """
        For any key in self.config_dict, if search_dict also has the key, use the corresponding value.
        Otherwise enumerate all values that key could take according to self.config_dict file.
        If search_dict contain any key that self.config_dict doesn't have all, that key is ignored.
        In addition, for each variable combination, list id corresponding to each run.
        For example, suppose self.total_combinations = 10 and
        we want to list ids corresponding to 4 runs, then the 5th variable combination
        corresponds to a 4-element list of ids [5, 15, 25, 35].

        :param
        search_dict: a dictionary containing key words
        num_runs: number of runs
        :return: the search result,
        a list of combinations of variables related to the key words
        """
        # Drop keys that are not swept variables; they cannot constrain a result.
        relevant = {k: v for k, v in search_dict.items() if k in self._keys_set}

        search_result_list = []
        for idx in range(self.total_combinations):
            combination = self.parse(idx)
            matches = all(
                key in combination and combination[key] == value
                for key, value in relevant.items()
            )
            if matches:
                search_result_list.append(
                    {
                        "ids": [
                            idx + run * self.total_combinations
                            for run in range(num_runs)
                        ],
                        **combination,
                    }
                )
        return search_result_list
