# Copyright © 2022 Arm Technology (China) Co. Ltd. All rights reserved.
# SPDX-License-Identifier: Apache-2.0


from ..op import *
import numpy as np


class QLinearAddMsOp(OpHasOneOutPort, OnnxOp):
    @classmethod
    def attributes(cls):
        return {1: {}}

    def __init__(self, graph, attr_dict=None):
        super(QLinearAddMsOp, self).__init__(graph, attr_dict)
        self.update_attributes(QLinearAddMsOp, attr_dict)
        assert self.check_required(), 'QLinearAddMsOp is missing a required parameter.'

    def __getattr__(self, item):
        try:
            ret = self.__dict__['_attr'][item].value
        except:
            ret = None
        try:
            if ret is None:
                input_names = ['A', 'A_scale', 'A_zero_point', 'B',
                               'B_scale', 'B_zero_point', 'C_scale', 'C_zero_point']
                if item in input_names:
                    item_idx = input_names.index(item)
                    inputs = self.get_input_tensors()
                    if len(inputs) > item_idx:
                        ret = inputs[item_idx]
                        if 'scale' in item:
                            ret = np.array(ret).astype(np.float32)
                        self.__dict__['_attr'][item] = Attribute(item, {'type': AttrType.TENSOR, 'value': ret})
                if ret is None and item in ('A_zero_point', 'B_zero_point', 'C_zero_point') and self.A is not None:
                    ret = np.array(0, dtype=self.A.dtype)
                    self.__dict__['_attr'][item] = Attribute(item, {'type': AttrType.TENSOR, 'value': ret})
        except:
            ret = None
        if ret is None:
            ret = super(QLinearAddMsOp, self).__getattr__(item)
        return ret

    def infer_shape(self):
        super(QLinearAddMsOp, self).infer_shape()
        inputs = self.get_input_tensors()
        assert len(inputs) >= 7, 'Meets invalid inputs length of QLinearAddMs op (%s)' % self.name
        float_a = (self.A.astype(np.int32) - self.A_zero_point) * self.A_scale
        float_b = (self.B.astype(np.int32) - self.B_zero_point) * self.B_scale
        float_y = np.add(float_a, float_b)
        out_min = np.iinfo(self.C_zero_point.dtype).min
        out_max = np.iinfo(self.C_zero_point.dtype).max
        out_tensor = np.clip(np.around(float_y / self.C_scale) + self.C_zero_point,
                             out_min, out_max).astype(self.C_zero_point.dtype)
        self.set_out_tensor(out_tensor)
