import vgg_network

import tensorflow as tf
import numpy as np
import scipy
import utils

from sys import stdout
from functools import reduce
from os.path import exists
import transform

class LossCalculator:

    def __init__(self, vgg, stylized_image):
        self.vgg = vgg
        self.transform_loss_net = vgg.net(vgg.preprocess(stylized_image))

    def content_loss(self, content_input_batch, content_layer, content_weight):
        content_loss_net = self.vgg.net(self.vgg.preprocess(content_input_batch))
        return content_weight * (2 * tf.nn.l2_loss(
                content_loss_net[content_layer] - self.transform_loss_net[content_layer]) /
                (_tensor_size(content_loss_net[content_layer])))

    def style_loss(self, style_image, style_layers, style_weight):
        style_image_placeholder = tf.placeholder('float', shape=style_image.shape)
        style_loss_net = self.vgg.net(style_image_placeholder)

        with tf.Session() as sess:
            style_loss = 0
            style_preprocessed = self.vgg.preprocess(style_image)

            for layer in style_layers:
                style_image_gram = self._calculate_style_gram_matrix_for(style_loss_net,
                                                                   style_image_placeholder,
                                                                   layer,
                                                                   style_preprocessed)

                input_image_gram = self._calculate_input_gram_matrix_for(self.transform_loss_net, layer)

                style_loss += (2 * tf.nn.l2_loss(input_image_gram - style_image_gram) / style_image_gram.size)

            return style_weight * (style_loss)

    def tv_loss(self, image, shape, tv_weight):
        # total variation denoising
        tv_y_size = _tensor_size(image[:,1:,:,:])
        tv_x_size = _tensor_size(image[:,:,1:,:])
        tv_loss = tv_weight * 2 * (
                (tf.nn.l2_loss(image[:,1:,:,:] - image[:,:shape[1]-1,:,:]) /
                    tv_y_size) +
                (tf.nn.l2_loss(image[:,:,1:,:] - image[:,:,:shape[2]-1,:]) /
                    tv_x_size))

        return tv_loss

    def _calculate_style_gram_matrix_for(self, network, image, layer, style_image):
        image_feature = network[layer].eval(feed_dict={image: style_image})
        image_feature = np.reshape(image_feature, (-1, image_feature.shape[3]))
        return np.matmul(image_feature.T, image_feature) / image_feature.size

    def _calculate_input_gram_matrix_for(self, network, layer):
        image_feature = network[layer]
        batch_size, height, width, number = map(lambda i: i.value, image_feature.get_shape())
        size = height * width * number
        image_feature = tf.reshape(image_feature, (batch_size, height * width, number))
        return tf.batch_matmul(tf.transpose(image_feature, perm=[0,2,1]), image_feature) / size



        self.total_variation_loss = tv_loss(self.stylized_image, self.batch_shape, tv_weight) / batch_size

        self.loss = self.content_loss  + self.style_loss + self.total_variation_loss




class FastStyleTransfer:
    CONTENT_LAYER = 'relu4_2'
    STYLE_LAYERS = ('relu1_1', 'relu2_1', 'relu3_1', 'relu4_1', 'relu5_1')

    def __init__(self, vgg_path,
                style_image, content_shape, content_weight,
                style_weight, tv_weight, batch_size):
        vgg = vgg_network.VGG(vgg_path)
        self.style_image = style_image
        self.batch_size = batch_size
        self.batch_shape = (batch_size,) + content_shape

        self.input_batch = tf.placeholder(tf.float32, shape=self.batch_shape, name="input_batch")
        self.stylized_image = transform.net(self.input_batch/255.0)

        loss_calculator = LossCalculator(vgg, self.stylized_image)

        self.content_loss = loss_calculator.content_loss(
                                        self.input_batch,
                                        self.CONTENT_LAYER,
                                        content_weight) / self.batch_size

        self.style_loss = loss_calculator.style_loss(
                                        self.style_image,
                                        self.STYLE_LAYERS,
                                        style_weight) / self.batch_size

        self.total_variation_loss = loss_calculator.tv_loss(
                                        self.stylized_image,
                                        self.batch_shape,
                                        tv_weight) / batch_size

        self.loss = self.content_loss  + self.style_loss + self.total_variation_loss


    def _current_loss(self, feed_dict):
        losses = {}
        losses['content'] = self.content_loss.eval(feed_dict=feed_dict)
        losses['style'] = self.style_loss.eval(feed_dict=feed_dict)
        losses['total_variation'] = self.total_variation_loss.eval(feed_dict=feed_dict)
        losses['total'] = self.loss.eval(feed_dict=feed_dict)
        return losses

    def train(self, content_training_images,
        learning_rate, epochs, checkpoint_iterations):

        def is_checkpoint_iteration(i):
            return (checkpoint_iterations and i % checkpoint_iterations == 0)

        def print_progress(i):
            stdout.write('Iteration %d\n' % (i + 1))

        best_loss = float('inf')
        best = None

        with tf.Session() as sess:
            train_step = tf.train.AdamOptimizer(learning_rate).minimize(self.loss)
            sess.run(tf.initialize_all_variables())
            iterations = 0
            for epoch in range(epochs):
                for i in range(0, len(content_training_images), self.batch_size):
                    print_progress(iterations)

                    batch = np.zeros(self.batch_shape, dtype=np.float32)

                    for j, img_path in enumerate(content_training_images[i: i+self.batch_size]):
                        batch[j] = utils.load_image(img_path, img_size=self.batch_shape[1:])

                    train_step.run(feed_dict={self.input_batch:batch})

                    if is_checkpoint_iteration(iterations):
                        yield (
                            iterations,
                            sess,
                            self.stylized_image.eval(feed_dict={self.input_batch:batch})[0],
                            self._current_loss({self.input_batch:batch})
                       )
                    iterations += 1

def calculate_style_gram_matrix_for(network, image, layer, style_image):
    image_feature = network[layer].eval(feed_dict={image: style_image})
    image_feature = np.reshape(image_feature, (-1, image_feature.shape[3]))
    return np.matmul(image_feature.T, image_feature) / image_feature.size

def calculate_input_gram_matrix_for(network, layer):
    image_feature = network[layer]
    batch_size, height, width, number = map(lambda i: i.value, image_feature.get_shape())
    size = height * width * number
    image_feature = tf.reshape(image_feature, (batch_size, height * width, number))
    return tf.batch_matmul(tf.transpose(image_feature, perm=[0,2,1]), image_feature) / size

def tv_loss(image, shape, tv_weight):
    # total variation denoising
    tv_y_size = _tensor_size(image[:,1:,:,:])
    tv_x_size = _tensor_size(image[:,:,1:,:])
    tv_loss = tv_weight * 2 * (
            (tf.nn.l2_loss(image[:,1:,:,:] - image[:,:shape[1]-1,:,:]) /
                tv_y_size) +
            (tf.nn.l2_loss(image[:,:,1:,:] - image[:,:,:shape[2]-1,:]) /
                tv_x_size))

    return tv_loss

def _tensor_size(tensor):
    from operator import mul
    return reduce(mul, (d.value for d in tensor.get_shape()), 1)


# wrapper
# transform network
