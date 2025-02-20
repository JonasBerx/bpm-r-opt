import csv
import datetime
import os
import re
import time

import pytz

from data_structures.simulation_info import SimulationInfo
from data_structures.solution_space import DeviationInfo
from support_modules.file_manager import load_simulation_result
from support_modules.file_manager import save_simulation_results
from support_modules.file_manager import temp_bpmn_file


def perform_prosimos_simulation(pools_info,
                                log_name,
                                simulations_count,
                                solution_index,
                                json_path,
                                model_file_path=temp_bpmn_file,
                                stat_out_path="./output_files/bimp_temp_files/output.csv",
                                starting_at=None):
    print("Running Simulation for Solution # %d (ID: %s) ..." % (solution_index, pools_info.id))
    simulated_info = load_simulation_result(log_name, pools_info)
    if simulated_info is not None:
        return simulated_info
    simulation_results = list()
    skipped = 0
    total_cases = 1000
    while simulations_count > 0:
        # Executing simulation with PROSIMOS
        # " --log_out_path ../bpm-r-opt/output_files/bimp_temp_files/log_out.csv "\
        starting_time = time.time()
        executable_string = "python ../Prosimos/diff_res_bpsim.py start-simulation --bpmn_path {model_file_path} " \
                            "--json_path {json_path} --total_cases {total_cases} --stat_out_path ../bpm-r-opt/output_files/bimp_temp_files/output.csv"\
            .format(
                model_file_path=model_file_path,
                json_path=json_path,
                total_cases=total_cases,
            )
        if starting_at is not None:
            executable_string += f"--starting_at {starting_at}"

        # executable_string+="& @type output_files\\bimp_temp_files\\output.csv > output_files\\bimp_temp_files\\output.txt"
        if os.system(executable_string):
            raise RuntimeError('simulation {} failed!')
        simulation_info = SimulationInfo(pools_info)
        simulation_info.simulation_time = time.time() - starting_time
        simulation_start_end = extract_simulation_dates_from_simulation_log(stat_out_path)
        if simulation_start_end[0] is None:
            skipped += 1
            if skipped > 10:
                print('BIMP-ERROR: Max cycle time for a simulation exceeded.')
                return None
            continue
        output_data = csv.reader(open(stat_out_path))
        simulation_info.update_simulation_period(simulation_start_end[0], simulation_start_end[1])

        output_section = 0

        for _, row in enumerate(output_data):
            if len(row) > 1:
                if row[0] == "Resource ID":
                    output_section = 1
                    continue
                elif row[0] == "Name":
                    output_section = 2
                    continue
                elif row[0] == "KPI":
                    output_section = 3
                    continue

                if output_section == 1:
                    if float(row[2]) < 0:
                        row[2] = 0
                    simulation_info.update_resource_utilization(row[0], float(row[2]))
                elif output_section == 2:
                    if row[0] in pools_info.task_pools:
                        simulation_info.add_task_statistics(pools_info.task_pools, row[0], float(row[8]), float(row[4]),
                                                            pools_info.pools[
                                                                pools_info.task_pools[row[0]]].get_total_cost())
                elif output_section == 3:
                    if row[0] == "cycle_time":
                        simulation_info.mean_process_cycle_time = float(row[3])

        simulation_results.append(simulation_info)
        simulations_count -= 1
        # x -= 1

    return estimate_median_absolute_deviation(pools_info, log_name, simulation_results)


def estimate_median_absolute_deviation(pools_info, log_name, simulation_results):
    by_cycle_time = sorted(simulation_results, key=lambda x: x.mean_process_cycle_time)
    by_duration = sorted(simulation_results, key=lambda x: x.simulation_duration())

    cycle_t_med = by_cycle_time[int(len(by_cycle_time) / 2)]
    duration_med = by_duration[int(len(by_duration) / 2)]

    c_times = list()
    duration = list()
    total_time = 0
    for i in range(0, len(by_cycle_time)):
        total_time += by_cycle_time[i].simulation_time
        c_times.append(abs(cycle_t_med.mean_process_cycle_time - by_cycle_time[i].mean_process_cycle_time))
        duration.append(abs(duration_med.simulation_duration() - by_duration[i].simulation_duration()))

    c_times = sorted(c_times)
    duration = sorted(duration)

    simulation_info = by_cycle_time[int(len(by_cycle_time) / 2)]
    simulation_info.deviation_info = DeviationInfo(c_times[int(len(c_times) / 2)], duration[int(len(duration) / 2)])

    print("Simulation Full Time:    %s" % str(datetime.timedelta(seconds=total_time)))
    print("Simulation Average Time: %s" % str(datetime.timedelta(seconds=(total_time / 15))))
    save_simulation_results(log_name, pools_info, simulation_results, simulation_info)

    return simulation_info


def extract_simulation_dates_from_simulation_log(file_path):
    simulation_start_date = None
    simulation_end_date = None
    with open(file_path) as file_reader:
        for line in file_reader:
            # TODO Change to how output of prosimos gives
            if 'started_at' in line:
                simulation_start_date = parse_date(line)
                if simulation_end_date is not None:
                    break
            elif 'completed_at' in line:
                simulation_end_date = parse_date(line)
                if simulation_start_date is not None:
                    break
    return [simulation_start_date, simulation_end_date]


def parse_date(date_str):
    return datetime.datetime.strptime(
        re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', date_str).group(), '%Y-%m-%d %H:%M:%S')
