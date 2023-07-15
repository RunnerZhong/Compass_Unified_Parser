# Copyright © 2022 Arm China Co. Ltd. All rights reserved.
# SPDX-License-Identifier: Apache-2.0


import copy
import os
import numpy as np
import onnx
import torch
import torch.onnx.symbolic_helper as helper
from torch.onnx import symbolic_opset9 as opset9
from multiprocessing import Process
from .utils import get_tuple_from_tensor_type
from ...logger import INFO, DEBUG, WARN, ERROR, FATAL
from ...common.utils import get_version
from ...common.defs import FLOAT_EQUAL


def convert_add_sub(g, input, other, alpha, op_type):
    if alpha and not FLOAT_EQUAL(helper._maybe_get_const(alpha, 'f'), 1):
        other = g.op('Mul', other, alpha)
    return g.op(op_type, input, other)


@helper.parse_args('v', 'v', 'v')
def convert_add(g, input, other, alpha=None):
    return convert_add_sub(g, input, other, alpha, 'Add')


@helper.parse_args('v', 'v', 'v')
def convert_rsub(g, input, other, alpha=None):
    return convert_add_sub(g, other, input, alpha, 'Sub')


@helper.parse_args('v', 'v', 'v')
def convert_sub(g, input, other, alpha=None):
    return convert_add_sub(g, input, other, alpha, 'Sub')


def convert_argmax_argmin(g, input, dim, keepdim, op_type):
    if helper._is_none(dim):
        flatten = helper._reshape_helper(g, input, [-1])
        output = g.op(op_type, flatten, axis_i=0, keepdims_i=False)
        if keepdim:
            input_shape = helper._get_tensor_sizes(input)
            output_shape = np.ones_like(input_shape)
            output = helper._reshape_helper(g, output, output_shape)
    else:
        dim = helper._parse_arg(dim, 'i')
        output = g.op(op_type, input, axis_i=dim, keepdims_i=keepdim)
    return output


@helper.parse_args('v', 'v', 'i')
def convert_argmax(g, input, dim=None, keepdim=False):
    return convert_argmax_argmin(g, input, dim, keepdim, 'ArgMax')


@helper.parse_args('v', 'v', 'i')
def convert_argmin(g, input, dim=None, keepdim=False):
    return convert_argmax_argmin(g, input, dim, keepdim, 'ArgMin')


def convert_bitshift(g, input, other, direction):
    input_dtype = input.type().dtype()
    if input_dtype.is_signed:
        FATAL("[Parser]: Only BitShift with unsigned input is supported to convert to onnx, but got type %s!" % str(input_dtype))
    return g.op('BitShift', input, other, direction_s=direction)


@helper.parse_args('v', 'v')
def convert_bitshift_left(g, input, other):
    return convert_bitshift(g, input, other, 'LEFT')


@helper.parse_args('v', 'v')
def convert_bitshift_right(g, input, other):
    return convert_bitshift(g, input, other, 'RIGHT')


@helper.parse_args('v', 'i')
def convert_channel_shuffle(g, input, groups):
    return g.op('custom::ChannelShuffle', input, group_i=groups)


@helper.parse_args('v', 'v', 'v', 'is', 'v', 'is', 'i')
def convert_conv(g, input, weight, bias, stride, padding, dilation, groups):
    # Support padding as string. Refer to https://github.com/pytorch/pytorch/pull/89107
    ret = None
    weight_shape = helper._get_tensor_sizes(weight)
    try:
        kernel_shape = weight_shape[2:]
    except:
        kernel_shape = None
    if kernel_shape is None or None in kernel_shape:
        ERROR('[Parser]: Meets invalid kernel shape of Conv op in convert_conv!')
        return ret

    args = [input, weight]
    need_separate_add = False
    if not helper._is_none(bias):
        if helper._get_tensor_rank(bias) == 1:
            args.append(bias)
        else:
            need_separate_add = True

    kwargs = {'kernel_shape_i': kernel_shape, 'strides_i': stride, 'dilations_i': dilation, 'group_i': groups}

    str_padding = helper._parse_arg(padding, 's')
    if str_padding in ('valid', 'same'):
        auto_pad = 'VALID' if str_padding == 'valid' else 'SAME_UPPER'
        kwargs.update({'auto_pad_s': auto_pad})
    else:
        padding = helper._parse_arg(padding, 'is')
        padding = padding + padding
        kwargs.update({'pads_i': padding})

    conv = g.op('Conv', *args, **kwargs)

    if need_separate_add:
        return g.op('Add', conv, bias)
    return conv


@helper.parse_args('v', 'i', 'i')
def convert_cumprod(g, input, dim, dtype):
    if dtype is not None:
        input = g.op('Cast', input, to_i=helper.scalar_type_to_onnx[dtype])
    return g.op('custom::CumProd', input, axis_i=dim)


@helper.parse_args('s', 'v', 's', 'v')
def convert_dict_construct(g, key_0, value_0, key_1=None, value_1=None):
    keys = ', '.join([key_0] + ([] if key_1 is None else [key_1]))
    WARN('[Parser]: prim::DictConstruct is unsupported and is changed to return a tensor or a list of tensors(key(s): %s) instead!' % keys)
    if value_1 is not None:
        g.registerOutput(value_0)  # value_0 is the first output of graph
        return g.op('Identity', value_1)  # value_1 is the second output of graph if this node is output
    return g.op('Identity', value_0)


def convert_quantized_add_relu(g, x, y, op_scale, op_zero_point):
    x, _, _, _ = helper.dequantize_helper(g, x)
    y, _, _, _ = helper.dequantize_helper(g, y)

    output = opset9.add(g, x, y)
    output = opset9.relu(g, output)

    return helper.quantize_helper(g, output, op_scale, op_zero_point)


@helper.parse_args('v', 'i', 'i')
@helper.quantized_args(True, False, False)
def convert_flatten(g, input, start_dim, end_dim):
    input_rank = helper._get_tensor_rank(input)
    if input_rank == 0:
        return helper._reshape_helper(g, input, [1])
    if input_rank == 1:
        return g.op('Identity', input)
    start_dim = (start_dim + input_rank) if start_dim < 0 else start_dim
    end_dim = (end_dim + input_rank) if end_dim < 0 else end_dim
    return helper._flatten_helper(g, input, start_dim, end_dim, input_rank)


@helper.parse_args('v', 'v', 'v', 'v', 'v', 'v')
def convert_gru_cell(g, input, hidden, w_ih, w_hh, b_ih, b_hh):
    from torch.onnx.symbolic_opset9 import _generic_rnn

    input = helper._unsqueeze_helper(g, input, [0])
    hidden = helper._unsqueeze_helper(g, hidden, [0])
    if helper._is_tensor(b_ih):
        weight = (w_ih, w_hh, b_ih, b_hh)
        has_biases = True
    else:
        weight = (w_ih, w_hh)
        has_biases = False
    _, h_out = _generic_rnn(g, 'GRU', input, hidden, weight,
                            has_biases, num_layers=1, dropout=False,
                            train=False, bidirectional=False,
                            batch_first=False)
    return helper._squeeze_helper(g, h_out, [0])


def convert_to_bool(g, input):
    input_dtype_str = input.type().scalarType()
    if input_dtype_str != 'Bool':
        input = g.op('Cast', input, to_i=torch._C._onnx.TensorProtoDataType.BOOL)
    return input


def convert_logical(g, input, other=None, op_type=''):
    assert len(op_type) > 0, 'Meets empty op_type in convert_logical!'
    if other is None:
        return g.op(op_type, convert_to_bool(g, input))
    return g.op(op_type, convert_to_bool(g, input), convert_to_bool(g, other))


@helper.parse_args('v')
def convert_logical_not(g, input):
    return convert_logical(g, input, op_type='Not')


@helper.parse_args('v', 'v')
def convert_equal(g, input, other):
    '''torch equal op is different with logical equal op. It returns scalar
    True if two tensors have the same size and elements, False otherwise.
    '''
    input_shape = helper._get_tensor_sizes(input)
    other_shape = helper._get_tensor_sizes(other)
    if input_shape != other_shape:
        return g.op('Constant', value_t=torch.tensor(False))
    equal = convert_logical(g, input, other, 'Equal')
    not_equal = g.op('Not', equal)
    reduce_sum = g.op('ReduceSum', not_equal, keepdims_i=0)
    return g.op('Not', reduce_sum)


@helper.parse_args('v', 'i', 'v', 'v')
def convert_quantized_cat(
    g,
    q_inputs,
    dim,
    op_scale,
    op_zero_point,
):
    unpacked_inputs = helper._unpack_list(q_inputs)
    dequantized = [
        helper.dequantize_helper(g, input)[0] for input in unpacked_inputs
    ]
    concatenated = g.op('Concat', *dequantized, axis_i=dim)
    return helper.quantize_helper(g, concatenated, op_scale, op_zero_point)


def convert_torch_to_onnx(model_path, params):
    def _export_to_onnx(model,
                        input_tensors,
                        onnx_model_path,
                        input_names,
                        output_names,
                        opset_version=None):
        # Note: Use operator_export_type=torch.onnx.OperatorExportTypes.ONNX_ATEN_FALLBACK
        # or torch.onnx.OperatorExportTypes.ONNX_ATEN for debug if export fails.
        # The failure could be caused by unexpected input shapes.
        torch.onnx.export(model,
                          input_tensors,
                          onnx_model_path,
                          input_names=input_names,
                          output_names=output_names,
                          opset_version=onnx_opset_version,
                          training=torch._C._onnx.TrainingMode.PRESERVE)
        return

    def _flatten_type(torch_type):
        output_types = []
        if isinstance(torch_type, torch._C.TupleType):
            for nested_out in torch_type.elements():
                output_types.extend(_flatten_type(nested_out))
        else:
            output_types.append(torch_type)
        return output_types

    # Check whether inputs and shapes are provided. They must be provided because we cannot get input
    # shapes info from the provided model.
    if not params['input_shapes']:
        FATAL('[Parser]: Input names and shapes must be provided in config file for TorchScript model!')

    # Load torchvision because some models in torchvision need it. If cannot import but model needs it,
    # error will be raised after torch.jit.load.
    try:
        import torchvision
    except:
        DEBUG('[Parser]: Fail to import torchvision!')
        pass

    # Load TorchScript model
    try:
        model = torch.jit.load(model_path)
    except Exception as e:
        FATAL('[Parser]: Fail to load model (%s) because %s! Only TorchScript format is supported.' %
              (model_path, str(e)))

    # Get onnx opset version to target
    # From https://onnxruntime.ai/docs/reference/compatibility.html,
    # for onnx version 1.x, onnx opset version=x+5
    onnx_version = str(get_version(onnx)).split('.')
    onnx_opset_version = (int(onnx_version[-1]) + 5) if int(onnx_version[0]) == 1 else None
    torch_version = str(torch.onnx.producer_version)
    if onnx_opset_version is not None:
        default_onnx_main_opset = None
        default_onnx_stable_opsets = []
        try:
            if torch_version.startswith('1.11'):
                default_onnx_main_opset = helper._onnx_main_opset
                default_onnx_stable_opsets = helper._onnx_stable_opsets
            elif torch_version >= '1.12.0':
                import torch.onnx._constants as Constant
                default_onnx_main_opset = Constant.onnx_main_opset
                default_onnx_stable_opsets = Constant.onnx_stable_opsets
        except Exception as e:
            DEBUG('[Parser]: Fail to get default onnx opset version because %s' % str(e))
        if default_onnx_main_opset is None:
            onnx_opset_version = None
        elif onnx_opset_version >= default_onnx_main_opset or onnx_opset_version not in default_onnx_stable_opsets:
            onnx_opset_version = default_onnx_main_opset
    if onnx_opset_version is None:
        onnx_opset_version = 9
    DEBUG('[Parser]: Will convert to onnx opset version (%s)!' % str(onnx_opset_version))

    # Convert torch op to non-custom onnx op
    if torch_version < '2.0.1':
        # The issue of argmax/argmin is fixed in torch 2.0.1.
        # Refer to https://github.com/pytorch/pytorch/pull/79503
        torch.onnx.register_custom_op_symbolic(
            'aten::argmax', convert_argmax, onnx_opset_version)
        torch.onnx.register_custom_op_symbolic(
            'aten::argmin', convert_argmin, onnx_opset_version)
        # The alpha issue of add/sub/rsub is fixed in torch 2.0.1.
        # Refer to https://github.com/pytorch/pytorch/pull/81736
        torch.onnx.register_custom_op_symbolic(
            'aten::add', convert_add, onnx_opset_version)
        torch.onnx.register_custom_op_symbolic(
            'aten::rsub', convert_rsub, onnx_opset_version)
        torch.onnx.register_custom_op_symbolic(
            'aten::sub', convert_sub, onnx_opset_version)
    if torch_version < '2.1.0':
        # The issue of string padding is fixed in latest torch.
        # Refer to https://github.com/pytorch/pytorch/pull/89107
        for conv_op in ('aten::conv1d', 'aten::conv2d', 'aten::conv3d'):
            torch.onnx.register_custom_op_symbolic(
                conv_op, convert_conv, onnx_opset_version)
        # The issue of logical_not is fixed in latest torch.
        # Refer to https://github.com/pytorch/pytorch/pull/96315
        torch.onnx.register_custom_op_symbolic(
            'aten::logical_not', convert_logical_not, onnx_opset_version)

    torch.onnx.register_custom_op_symbolic(
        'aten::bitwise_left_shift', convert_bitshift_left, onnx_opset_version)
    torch.onnx.register_custom_op_symbolic(
        'aten::bitwise_right_shift', convert_bitshift_right, onnx_opset_version)
    torch.onnx.register_custom_op_symbolic(
        'aten::equal', convert_equal, onnx_opset_version)
    torch.onnx.register_custom_op_symbolic(
        'aten::flatten', convert_flatten, onnx_opset_version)
    torch.onnx.register_custom_op_symbolic(
        'aten::gru_cell', convert_gru_cell, onnx_opset_version)

    # for quantized Ops
    torch.onnx.register_custom_op_symbolic(
        'quantized::add_relu', convert_quantized_add_relu, onnx_opset_version)
    torch.onnx.register_custom_op_symbolic(
        'quantized::cat', convert_quantized_cat, onnx_opset_version)

    # Only convert prim::DictConstruct to Identity when it's output node.
    dict_nodes = model.graph.findAllNodes('prim::DictConstruct')
    model_output_names = [out.debugName() for out in model.graph.outputs()]
    if dict_nodes and all(node.output().debugName() in model_output_names for node in dict_nodes):
        torch.onnx.register_custom_op_symbolic('prim::DictConstruct', convert_dict_construct, onnx_opset_version)

    # Convert torch op to custom onnx op
    torch.onnx.register_custom_op_symbolic('aten::channel_shuffle', convert_channel_shuffle, onnx_opset_version)
    torch.onnx.register_custom_op_symbolic('aten::cumprod', convert_cumprod, onnx_opset_version)

    # Get input_tensors and input_names
    input_names = []
    tensor_list = []
    input_info_dict = copy.deepcopy(params['input_shapes'])
    input_dtype = params['input_dtype']
    for idx, (input_name, input_shape) in enumerate(input_info_dict.items()):
        if len(input_name) >= 1 and input_name[0].isdigit():  # Starting with numbers is not legal in pytorch
            new_input_name = 'input_' + input_name
            WARN('[Parser]: Input name %s is invalid; rename it to %s!' % (input_name, new_input_name))
            params['input_shapes'].pop(input_name)
            params['input_shapes'][new_input_name] = input_shape
            input_name = new_input_name
        input_names.append(input_name)
        assert len(input_dtype) > idx, 'Meets invalid input_dtype in convert_torch_to_onnx'
        try:
            tensor_dtype = getattr(torch, input_dtype[idx])
            INFO('[Parser]: Input dtype of input %s is set to %s!' % (input_name, input_dtype[idx]))
        except Exception as e:
            tensor_dtype = torch.float32
            WARN('[Parser]: Input dtype %s is changed to float32 because %s' % (input_dtype[idx], str(e)))
        if 'float' in str(tensor_dtype):
            tensor = torch.randn(input_shape, dtype=tensor_dtype)
        else:
            tensor = torch.zeros(input_shape, dtype=tensor_dtype)
        tensor_list.append(tensor)

    input_tensors = ()
    input_index = 0
    for inp in model.graph.inputs():
        tensors, input_index = get_tuple_from_tensor_type(inp.type(), tensor_list, input_index)
        if len(tensors) > 0:
            input_tensors += tensors

    # Get output_names. When the output is a tuple, it's actually multiple outputs constructed in that tuple.
    output_names = []
    for out_idx, out in enumerate(model.graph.outputs()):
        out_name = out.debugName() + '_' + str(out_idx) + '_'
        if isinstance(out.type(), torch._C.DictType):
            inputs_num = len([inp for inp in out.node().inputs()])
            outputs_num = inputs_num // 2
        else:
            outputs_num = len(_flatten_type(out.type()))
        output_names.extend([out_name + str(idx) for idx in range(outputs_num)])
    for idx, output_name in enumerate(output_names):
        if output_name[0].isdigit():
            output_names[idx] = 'output_' + output_name

    # Get the file name of the onnx model to be exported
    onnx_model_path = os.path.join(params.get('output_dir', './'),
                                   os.path.basename(model_path) + '.onnx')
    INFO('[Parser]: Convert TorchScript (%s) to onnx model...' % model_path)

    # Call torch.onnx.export to convert TorchScript model to onnx model
    exit_code = 1
    try:
        # Fix hangs issue by set_num_threads if multiprocessing is used.
        # Refer to https://github.com/pytorch/pytorch/issues/36191
        torch.set_num_threads(1)
        # # Uncomment the following line to debug this code and torch.onnx.export:
        # _export_to_onnx(model, input_tensors, onnx_model_path, input_names, output_names, onnx_opset_version)
        process = Process(target=_export_to_onnx, args=(model,
                                                        input_tensors,
                                                        onnx_model_path,
                                                        input_names,
                                                        output_names,
                                                        onnx_opset_version))
        process.start()
        process.join()
        exit_code = process.exitcode
        try:
            process.close()
        except Exception as e:
            DEBUG('[Parser]: Fail to close process because %s' % str(e))
    except Exception as e:
        FATAL('[Parser]: Fail to convert model (%s) to onnx because %s' % (model_path, str(e)))

    if exit_code != 0:
        FATAL('[Parser]: Fail to convert model (%s) to onnx! Suggest to set env var PYTORCH_JIT_LOG_LEVEL=onnx for debug!' % model_path)

    INFO('[Parser]: Torch model has been converted to onnx model (%s) with opset version (%d)!' %
         (onnx_model_path, 'default' if onnx_opset_version is None else onnx_opset_version))

    # Update params
    updated_params = copy.deepcopy(params)
    updated_params.update({'input_model': onnx_model_path,
                           'input_names': input_names,
                           'input_shapes': params['input_shapes'],
                           'output_names': [],
                           'output_tensor_names': output_names,
                           'model_type': 'torch'})

    # Return onnx model path and updated params
    return onnx_model_path, updated_params
