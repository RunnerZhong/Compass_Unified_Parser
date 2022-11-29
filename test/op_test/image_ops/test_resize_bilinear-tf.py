import numpy as np

import tensorflow.compat.v1 as tf

from utils.run import run_parser


def create_resize_bilinear_model(pb_file_path, input_size, align_corners=False, half_pixel_centers=False):
    ''' Create tensorflow model for resize_bilinear op.
    '''
    with tf.Session(graph=tf.Graph()) as sess:
        x = tf.placeholder(tf.float32, shape=input_size, name='X')
        op1 = tf.raw_ops.ResizeBilinear(images=x, size=[65, 65],
                                        align_corners=align_corners,
                                        half_pixel_centers=half_pixel_centers,
                                        name='resize_bilinear')
        y = tf.add(op1, 10.0, name='Y')

        sess.run(tf.global_variables_initializer())
        constant_graph = tf.graph_util.convert_variables_to_constants(
            sess, sess.graph_def, ['Y'])

        # save to pb file
        with tf.gfile.GFile(pb_file_path, mode='wb') as f:
            f.write(constant_graph.SerializeToString())


TEST_NAME = 'resize_bilinear'
input_shape = [1, 12, 20, 256]

# Generate input data
feed_dict = dict()
feed_dict['X:0'] = np.random.ranf(input_shape).astype(np.float32)

for align_corners in (True, False):
    for half_pixel_centers in (True, False):
        model_path = '-'.join([TEST_NAME, str(align_corners), str(half_pixel_centers)]) + '.pb'
        # Create model
        create_resize_bilinear_model(model_path, input_shape)

        # Run tests with parser and compare result with runtime
        exit_status = run_parser(
            model_path, feed_dict, model_type='tf', verify=True)
        assert exit_status
