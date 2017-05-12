import os,glob

import numpy as np
import tensorflow as tf
import SimpleITK as sitk


def image_scaling(img, label):
    """
    Randomly scales the images between 0.5 to 1.5 times the original size.

    Args:
      img: Training image to scale.
      label: Segmentation mask to scale.
    """
    
    scale = tf.random_uniform([1], minval=0.5, maxval=1.5, dtype=tf.float32, seed=None)
    h_new = tf.to_int32(tf.multiply(tf.to_float(tf.shape(img)[0]), scale))
    w_new = tf.to_int32(tf.multiply(tf.to_float(tf.shape(img)[1]), scale))
    new_shape = tf.squeeze(tf.stack([h_new, w_new]), squeeze_dims=[1])
    img = tf.image.resize_images(img, new_shape)
    label = tf.image.resize_nearest_neighbor(tf.expand_dims(label, 0), new_shape)
    label = tf.squeeze(label, squeeze_dims=[0])
   
    return img, label

def image_mirroring(img, label):
    """
    Randomly mirrors the images.

    Args:
      img: Training image to mirror.
      label: Segmentation mask to mirror.
    """
    
    distort_left_right_random = tf.random_uniform([1], 0, 1.0, dtype=tf.float32)[0]
    mirror = tf.less(tf.stack([1.0, distort_left_right_random, 1.0]), 0.5)
    mirror = tf.boolean_mask([0, 1, 2], mirror)
    img = tf.reverse(img, mirror)
    label = tf.reverse(label, mirror)
    return img, label

def random_crop_and_pad_image_and_labels(image, label, crop_h, crop_w, ignore_label=255):
    """
    Randomly crop and pads the input images.

    Args:
      image: Training image to crop/ pad.
      label: Segmentation mask to crop/ pad.
      crop_h: Height of cropped segment.
      crop_w: Width of cropped segment.
      ignore_label: Label to ignore during the training.
    """

    label = tf.cast(label, dtype=tf.float32)
    label = label - ignore_label # Needs to be subtracted and later added due to 0 padding.
    combined = tf.concat(axis=2, values=[image, label]) 
    image_shape = tf.shape(image)
    combined_pad = tf.image.pad_to_bounding_box(combined, 0, 0, tf.maximum(crop_h, image_shape[0]), tf.maximum(crop_w, image_shape[1]))
    
    last_image_dim = tf.shape(image)[-1]
    last_label_dim = tf.shape(label)[-1]
    combined_crop = tf.random_crop(combined_pad, [crop_h,crop_w,4])
    img_crop = combined_crop[:, :, :last_image_dim]
    label_crop = combined_crop[:, :, last_image_dim:]
    label_crop = label_crop + ignore_label
    label_crop = tf.cast(label_crop, dtype=tf.uint8)
    
    # Set static shape so that tensorflow knows shape at compile time. 
    img_crop.set_shape((crop_h, crop_w, 3))
    label_crop.set_shape((crop_h,crop_w, 1))
    return img_crop, label_crop  

def read_labeled_image_list(data_dir, mask_dir):
    """Reads txt file containing paths to images and ground truth masks.
    
    Args:
      data_dir: path to the directory with images and masks.
      data_list: path to the file with lines of the form '/path/to/image /path/to/mask'.
       
    Returns:
      Two lists with all file names for images and masks, respectively.
    """

    images = []
    masks = []
    # data_dir = "/home/zack/Data/LUNA16/"
    # mask_dir = "/home/zack/Data/LUNA16/seg-lungs-LUNA16"

    for i in xrange(8):
        os.chdir(data_dir + "subset" + str(i))
        for file in glob.glob("*.mhd"):
            images.append(os.path.join(data_dir + "subset" + str(i), file))
            masks.append(os.path.join(mask_dir, file))
    return images, masks

def read_images_from_disk(input_queue, input_size, random_scale, random_mirror, ignore_label, img_mean): # optional pre-processing arguments
    """Read one image and its corresponding mask with optional pre-processing.
    
    Args:
      input_queue: tf queue with paths to the image and its mask.
      input_size: a tuple with (height, width) values.
                  If not given, return images of original size.
      random_scale: whether to randomly scale the images prior
                    to random crop.
      random_mirror: whether to randomly mirror the images prior
                    to random crop.
      ignore_label: index of label to ignore during the training.
      img_mean: vector of mean colour values.
      
    Reprint turns:
      Two tensors: the decoded image and its mask.
    """
    itkimg = sitk.ReadImage(input_queue[0])
    img=sitk.GetArrayFromImage(itkimg)
    random_anchor = np.random.randint(1,img.shape[0]-1)


    img = img[(random_anchor-1,random_anchor,random_anchor+1),:,:]
    img =np.transpose(img,(1,2,0))
    img = tf.cast(img, dtype=tf.float32)
    # Extract mean.
    img -= img_mean

    itklabel = sitk.ReadImage(input_queue[1])
    label = sitk.GetArrayFromImage(itklabel)
    label=label[random_anchor,:,:]

    label =np.expand_dims(label,axis=2)


    if input_size is not None:
        h, w = input_size

        # Randomly scale the images and labels.
        if random_scale:
            img, label = image_scaling(img, label)

        # Randomly mirror the images and labels.
        if random_mirror:
            img, label = image_mirroring(img, label)

        # Randomly crops the images and labels.
        img, label = random_crop_and_pad_image_and_labels(img, label, h, w, ignore_label)

    return img, label

class ImageReader_LUNA16(object):
    '''Generic ImageReader which reads images and corresponding segmentation
       masks from the disk, and enqueues them into a TensorFlow queue.
    '''

    def __init__(self, data_dir, mask_dir, input_size,
                 random_scale, random_mirror, ignore_label, img_mean, coord):
        '''Initialise an ImageReader.
        
        Args:
          data_dir: path to the directory with images and masks.
          data_list: path to the file with lines of the form '/path/to/image /path/to/mask'.
          input_size: a tuple with (height, width) values, to which all the images will be resized.
          random_scale: whether to randomly scale the images prior to random crop.
          random_mirror: whether to randomly mirror the images prior to random crop.
          ignore_label: index of label to ignore during the training.
          img_mean: vector of mean colour values.
          coord: TensorFlow queue coordinator.
        '''
        self.data_dir = data_dir
        self.mask_dir = mask_dir
        self.input_size = input_size
        self.coord = coord
        self.random_scale = random_scale
        self.random_mirror = random_mirror
        self.ignore_label = ignore_label
        self.img_mean = img_mean
        
        self.image_list, self.label_list = read_labeled_image_list(self.data_dir, self.mask_dir)

        assert (len(self.image_list) == len(self.label_list))
        self.sample_size = len(self.image_list)


    def dequeue(self, num_elements):
        '''Pack images and labels into a batch.
        
        Args:
          num_elements: the batch size.
          
        Returns:
          Two tensors of size (batch_size, h, w, {3, 1}) for images and masks.'''
        image_batch=[]
        label_batch=[]
        for i in xrange(num_elements):
            self.current_sample=np.random.randint(0,self.sample_size)
            self.image, self.label = read_images_from_disk([self.image_list[self.current_sample],self.label_list[self.current_sample]], self.input_size, self.random_scale, self.random_mirror, self.ignore_label, self.img_mean)
            image_batch.append(self.image)
            label_batch.append(self.label)

        
        image_batch = tf.convert_to_tensor(image_batch)
        label_batch = tf.convert_to_tensor(label_batch)
        return image_batch, label_batch
