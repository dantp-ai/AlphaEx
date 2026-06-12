#######################################################################
# Copyright (C) 2019 Yi Wan(wan6@ualberta.ca)                         #
# Permission given to modify the code as long as you keep this        #
# declaration at the top                                              #
#######################################################################
import os

from alphaex.sweeper import Sweeper


def test_sweeper():
    cfg_dir = "test/cfg"
    sweep_file_name = "variables.json"
    num_runs = 10
    # test Sweeper.parse
    sweeper = Sweeper(os.path.join(cfg_dir, sweep_file_name))
    for sweep_id in range(0, sweeper.total_combinations * num_runs):
        rtn_dict = sweeper.parse(sweep_id)

        report = (
            f"idx: {sweep_id} \n"
            f"run: {rtn_dict.get('run', None)}\n"
            f"simulator: {rtn_dict.get('simulator', None)}\n"
            f"algorithm: {rtn_dict.get('algorithm', None)}\n"
            f"param1: {rtn_dict.get('param1', None)}\n"
            f"param2: {rtn_dict.get('param2', None)} \n"
            f"param3: {rtn_dict.get('param3', None)}\n"
            f"param4: {rtn_dict.get('param4', None)}\n"
            f"param5: {rtn_dict.get('param5', None)}\n"
            f"param6: {rtn_dict.get('param6', None)}\n"
        )
        print(report)

        # test Sweeper.search
    print(
        sweeper.search(
            {
                "param1": "param1_3",
                "param4": True,
                "a_key_not_in_sweeper": 0,
                "the_other_key_not_in_sweeper": True,
            },
            num_runs,
        )
    )


if __name__ == "__main__":
    test_sweeper()
