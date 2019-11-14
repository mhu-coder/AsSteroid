"""
Wham Dataset class.
@author : Manuel Pariente, Inria-Nancy
"""
import torch
from torch.utils import data
import json
import os
import numpy as np
import soundfile as sf

DATASET = 'WHAM'
# WHAM tasks
enh_single = {'mixture': 'mix_single',
              'sources': ['s1'],
              'infos': ['noise'],
              'default_nsrc': 1}
enh_both = {'mixture': 'mix_both',
            'sources': ['mix_clean'],
            'infos': ['noise'],
            'default_nsrc': 1}
sep_clean = {'mixture': 'mix_both',
             'sources': ['s1', 's2'],
             'infos': [],
             'default_nsrc': 2}
sep_noisy = {'mixture': 'mix_both',
             'sources': ['s1', 's2'],
             'infos': ['noise'],
             'default_nsrc': 2}

WHAM_TASKS = {'enhance_single': enh_single,
              'enhance_both': enh_both,
              'sep_clean': sep_clean,
              'sep_noisy': sep_noisy}
# Aliases.
WHAM_TASKS['enh_single'] = WHAM_TASKS['enhance_single']
WHAM_TASKS['enh_both'] = WHAM_TASKS['enhance_both']


class WhamDataset(data.Dataset):
    """ Dataset class for WHAM source separation and speech enhancement tasks.
    Args:
        json_dir: String, the path to the directory containing the json files.
        task: String, one of `"enh_single"`, `"enh_both"`, `"sep_clean"` or
            `"sep_noisy"`.
            `"enh_single"` for single speaker speech enhancement.
            `"enh_both"` for multi speaker speech enhancement.
            `"sep_clean"` for two-speaker clean source separation.
            `"sep_noisy"` for two-speaker noisy source separation.
        sample_rate: Integer. The sampling rate of the wav files.
        segment: Float. Length of the segments used for training, in seconds.
        nondefault_nsrc: Integer. Number of sources in the training targets.
            If None, defaults to one for enhancement tasks and two for
            separation tasks.
    """
    def __init__(self, json_dir, task, sample_rate=8000, segment=4.0,
                 nondefault_nsrc=None):
        super(WhamDataset, self).__init__()
        if task not in WHAM_TASKS.keys():
            raise ValueError('Unexpected task {}, expected one of '
                             '{}'.format(task, WHAM_TASKS.keys()))
        # Task setting
        self.json_dir = json_dir
        self.task = task
        self.task_dict = WHAM_TASKS[task]
        self.sample_rate = sample_rate
        self.seg_len = segment
        if not nondefault_nsrc:
            self.n_src = self.task_dict['default_nsrc']
        else:
            assert nondefault_nsrc >= self.task_dict['default_nsrc']
            self.n_src = nondefault_nsrc
        # Load json files
        mix_json = os.path.join(json_dir, self.task_dict['mixture'] + '.json')
        sources_json = [os.path.join(json_dir, source + '.json') for
                        source in self.task_dict['sources']]
        with open(mix_json, 'r') as f:
            mix_infos = json.load(f)
        sources_infos = []
        for src_json in sources_json:
            with open(src_json, 'r') as f:
                sources_infos.append(json.load(f))
        # Filter out short utterances
        orig_len = len(mix_infos)
        self.seg_len = int(segment * sample_rate)
        drop_utt, drop_len = 0, 0
        for i in range(len(mix_infos) - 1, -1, -1):  # Go backward
            if mix_infos[i][1] < self.seg_len:
                drop_utt += 1
                drop_len += mix_infos[i][1]
                del mix_infos[i]
                for src_inf in sources_infos:
                    del src_inf[i]

        print("Drop {} utts({:.2f} h) from {} (shorter than {} samples)".format(
            drop_utt, drop_len/sample_rate/36000, orig_len, self.seg_len))
        self.mix = mix_infos
        # Handle the case n_src > default_nsrc
        while len(sources_infos) < self.n_src:
            sources_infos.append([None for _ in range(len(self.mix))])
        self.sources = sources_infos

    def __add__(self, wham):
        if self.n_src != wham.n_src:
            raise ValueError('Only datasets having the same number of sources'
                             'can be added together. Received '
                             '{} and {}'.format(self.n_src, wham.n_src))
        if self.seg_len != wham.seg_len:
            self.seg_len = min(self.seg_len, wham.seg_len)
            print('Segment length mismatched between the two Dataset'
                  'passed one the smallest to the sum.')
        self.mix = self.mix + wham.mix
        self.sources = [a + b for a, b in zip(self.sources, wham.sources)]

    def __len__(self):
        return len(self.mix)

    def __getitem__(self, idx):
        # Random start
        if self.mix[idx][1] == self.seg_len:
            rand_start = 0
        else:
            rand_start = np.random.randint(0, self.mix[idx][1] - self.seg_len)
        # Load mixture
        x, _ = sf.read(self.mix[idx][0], start=rand_start,
                       stop=rand_start + self.seg_len, dtype='float32')
        seg_len = torch.as_tensor([len(x)])
        # Load sources
        source_arrays = []
        for src in self.sources:
            if src[idx] is None:
                # Target is filled with zeros id n_src > default_nsrc
                s = np.zeros((seg_len, ))
            else:
                s, _ = sf.read(src[idx][0], start=rand_start,
                               stop=rand_start + self.seg_len, dtype='float32')
            source_arrays.append(s)
        sources = torch.from_numpy(np.vstack(source_arrays))
        return torch.from_numpy(x), sources, {'seg_len': seg_len}
