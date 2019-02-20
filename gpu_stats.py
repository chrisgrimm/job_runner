import subprocess
import numpy as np
import re
import time
import multiprocessing as mp
import tempfile

class SSHSession:

    def __init__(self, username, address):
        self.proc = subprocess.Popen([f'ssh {username}@{address}'], stdin=subprocess.PIPE,
                                     bufsize=0, stdout=subprocess.PIPE, shell=True)
        self.run_command(['echo', 'setup_up_complete'])
        self.username = username
        self.address = address

    def shutdown(self):
        self.proc.terminate()

    def run_command(self, command_list, finish_string='COMMAND_IS_FINISHED'):
        all_output = ''
        current_output = None
        command = ' '.join(command_list)
        full_string = f'{command} & wait; echo "{finish_string}"\n'
        self.proc.stdin.write(full_string.encode())
        while current_output != finish_string:
            current_output = self.proc.stdout.readline().decode('utf-8').strip()
            if current_output != finish_string:
                all_output += (current_output + '\n')
            else:
                return all_output


class RLDLSession(SSHSession):

    def __init__(self, username, address):
        super().__init__(username, address)

        # manager and shared list references for the session.
        self.manager = mp.Manager()
        self.gpu_fans_list = self.manager.list([])
        self.mem_percs_list = self.manager.list([])
        self.gpu_utils_list = self.manager.list([])

        # parameters to control data collection amounts and rates
        self.running_average = 5
        self.time_between_polls = 1

        self.start_update_thread()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()

    def shutdown(self):
        self.gpu_process.terminate()
        self.gpu_process.join()
        super().shutdown()


    def _get_gpu_info(self):
        info = self.run_command(['nvidia-smi'])
        gpu_fans = []
        mem_percs = []
        gpu_utils = []
        #print(info)
        for line in info.split('\n'):
            #print('line', line)
            match = re.match(r'^.+?(\d+)\%.+?(\d+)MiB.+?\/.+?(\d+)MiB.+?(\d+)\%.+?$', line)
            if not match:
                continue
            (gpu_fan, mem_numer, mem_denom, gpu_util) = match.groups()
            gpu_fans.append(float(gpu_fan) / 100)
            mem_percs.append(float(mem_numer) / float(mem_denom))
            gpu_utils.append(float(gpu_util) / 100)
        return gpu_fans, mem_percs, gpu_utils

    def get_gpu_info_thread(self, lock, gpu_fans_list, mem_percs_list, gpu_utils_list):
        while True:
            gpu_fans, mem_percs, gpu_utils = self._get_gpu_info()
            with lock:
                gpu_fans_list.append(gpu_fans)
                mem_percs_list.append(mem_percs)
                gpu_utils_list.append(gpu_utils)
                if len(gpu_fans_list) > self.running_average:
                    gpu_fans_list.pop(0)
                if len(mem_percs_list) > self.running_average:
                    mem_percs_list.pop(0)
                if len(gpu_utils_list) > self.running_average:
                    gpu_utils_list.pop(0)
            time.sleep(self.time_between_polls)


    def start_update_thread(self):
        lock = mp.Lock()
        self.gpu_process = mp.Process(target=self.get_gpu_info_thread,
                                      args=(lock, self.gpu_fans_list, self.mem_percs_list, self.gpu_utils_list))
        self.gpu_process.start()


    def get_gpu_info(self):
        gpu_fans_list = self.gpu_fans_list._getvalue()
        mem_percs_list = self.mem_percs_list._getvalue()
        gpu_utils_list = self.gpu_utils_list._getvalue()

        gpu_fans_avg = np.mean(np.array(gpu_fans_list), axis=0).tolist()
        mem_percs_avg = np.mean(np.array(mem_percs_list), axis=0).tolist()
        gpu_utils_avg = np.mean(np.array(gpu_utils_list), axis=0).tolist()
        assert len(gpu_fans_avg) == len(mem_percs_avg) == len(gpu_utils_avg)
        gpu_stats = []
        for i in range(len(gpu_fans_avg)):
            gpu_stats.append({'fan': gpu_fans_avg[i], 'mem_perc': mem_percs_avg[i], 'gpu_util': gpu_utils_avg[i]})
        return gpu_stats




class MultiRLDLManager:

    def __init__(self, username_list, address_list):
        self.rldl_sessions = [RLDLSession(username, address) for username, address in zip(username_list, address_list)]
        self.max_gpu_mem = 0.9
        self.max_gpu_util = 0.9

    def get_valid_devices(self):
        valid_devices = []
        for sess in self.rldl_sessions:
            gpu_infos = sess.get_gpu_info()
            for gpu_num, gpu in enumerate(gpu_infos):
                if gpu['mem_perc'] < self.max_gpu_mem and gpu['gpu_util'] < self.max_gpu_util:
                    valid_devices.append((sess.address, gpu_num))
        return valid_devices









if __name__ == '__main__':
    # line = ' | 45%   60C    P2    80W / 250W |   6149MiB / 11178MiB |     22%      Default |'
    # match = re.match(r'^.+?(\d+)\%.+?(\d+)MiB.+?\/.+?(\d+)MiB.+?(\d+)\%.+?$', line)
    # print(match.groups())
    with RLDLSession('crgrimm', 'rldl11.eecs.umich.edu') as sess:
        while True:
            time.sleep(2)
            print(sess.get_gpu_info())




