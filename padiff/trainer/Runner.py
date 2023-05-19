# Copyright (c) 2022 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from .trainer_utils import report_guard, debug_print_struct, register_hooker
from ..utils import (
    log,
    max_diff,
    tensors_mean,
    log_file,
    remove_inplace,
)

import os


class Runner(object):
    def __init__(self, models, loss_fn, layer_map, options):
        self.models = models
        self.options = options
        self.loss_fn = loss_fn
        self.layer_map = layer_map
        self.reports = [None, None]

        remove_inplace(models)

        if os.getenv("PADIFF_CUDA_MEMORY") != "OFF":
            self.devices = [model.get_device() for model in self.models]
            for model in self.models:
                model.to_cpu()

    def set_report(self, reports):
        reports[0].layer_map = self.layer_map
        reports[1].layer_map = self.layer_map
        self.reports = reports

    def forward_step(self, example_inp):
        with report_guard(self.reports):
            model_idx = 0
            with register_hooker(self, model_idx):
                try:
                    torch_output = self.models[model_idx](**(example_inp[model_idx]))
                    if self.options["use_loss"]:
                        loss = self.loss_fn[model_idx](torch_output)
                        self.reports[model_idx].set_loss(loss)
                    else:
                        loss = tensors_mean(torch_output, self.models[model_idx].model_type)
                    if self.options["diff_phase"] == "both" or self.options["diff_phase"] == "backward":
                        loss.backward()
                except Exception as e:
                    raise RuntimeError(
                        "Exception is thrown while running forward of first model, please check the legality of module.\n{}".format(
                            type(e).__name__ + ":  " + str(e)
                        )
                    )

            model_idx = 1
            with register_hooker(self, model_idx):
                try:
                    paddle_output = self.models[model_idx](**(example_inp[model_idx]))
                    if self.options["use_loss"]:
                        loss = self.loss_fn[model_idx](paddle_output)
                        self.reports[model_idx].set_loss(loss)
                    else:
                        loss = tensors_mean(paddle_output, self.models[model_idx].model_type)
                    if self.options["diff_phase"] == "both" or self.options["diff_phase"] == "backward":
                        loss.backward()
                except Exception as e:
                    raise RuntimeError(
                        "Exception is thrown while running forward of second model, please check the legality of module.\n{}".format(
                            type(e).__name__ + ":  " + str(e)
                        )
                    )

        if not self.options["single_step"]:
            log("Max elementwise output diff is {}".format(max_diff(paddle_output, torch_output)))

    def property_print(self, idx, mode=None):
        strs = debug_print_struct(self.reports[idx].stack.root)
        if mode is None:
            print(strs)
        else:
            path = log_file("debug_report", "w", strs)
            print(f"debug log path: {path}")
