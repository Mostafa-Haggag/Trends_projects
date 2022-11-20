from __future__ import print_function
from PIL import Image
import os
import os.path
import numpy as np
import sys
if sys.version_info[0] == 2:
    import cPickle as pickle
else:
    import pickle

import random
import torch
import torch.utils.data as data
from .utils import download_url, check_integrity
from .utils import TransformTwice, TransformKtimes, RandomTranslateWithReflect, TwoStreamBatchSampler
from .concat import ConcatDataset
import torchvision.transforms as transforms

class CIFAR10(data.Dataset):# this is class dataset
    """`CIFAR10 <https://www.cs.toronto.edu/~kriz/cifar.html>`_ Dataset.

    Args:
        root (string): Root directory of dataset where directory
            ``cifar-10-batches-py`` exists or will be saved to if download is set to True.
        train (bool, optional): If True, creates dataset from training set, otherwise
            creates from test set.
        transform (callable, optional): A function/transform that takes in an PIL image
            and returns a transformed version. E.g, ``transforms.RandomCrop``
        target_transform (callable, optional): A function/transform that takes in the
            target and transforms it.
        download (bool, optional): If true, downloads the dataset from the internet and
            puts it in root directory. If dataset is already downloaded, it is not
            downloaded again.

    """
    # all the following stuff are training variables
    base_folder = 'cifar-10-batches-py'# name of the folder that you should have
    url = "https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz"# you get from this website
    filename = "cifar-10-python.tar.gz"
    tgz_md5 = 'c58f30108f718f92721af3b95e74349a'
    # you can find all the following files in following directory after running the first script download_pretrained_models_dataset.sh
    # --> autoNovel/data/datasets/CIFAR/cifar-10-batches-py
    train_list = [
        ['data_batch_1', 'c99cafc152244af753f735de768cd75f'],
        ['data_batch_2', 'd4bba439e000b95fd0a9bffe97cbabec'],
        ['data_batch_3', '54ebc095f3ab1f0389bbae665268c751'],
        ['data_batch_4', '634d18415352ddfa80567beed471001a'],
        ['data_batch_5', '482c414d41f54cd18b22e5b47cb7c3cb'],
    ]# different files for training

    test_list = [
        ['test_batch', '40351d587109b95175f43aff81a1287e'],
    ]#this file is the test file 
    meta = {
        'filename': 'batches.meta',
        'key': 'label_names',
        'md5': '5ff9c542aee3614f3951f8cda6e48888',
    }# the meta file contains the labels in general capittooooo ragaaa??

    def __init__(self, root, split='train+test',
                 transform=None, target_transform=None,
                 download=False, target_list = range(5)):
        # root is the directory where the data set is locatied. which is in this case ./data/datasets/CIFAR/ capitto ?
        #you pass the transformations that you want to do, download is to downlaod ddata set
        # target list is the range of the labels that you have. for example for labeled you are passing labels from0 to 4 and 
        self.root = os.path.expanduser(root)
        self.transform = transform# group of transformations
        self.target_transform = target_transform# it is a range
        if download:# if you turn on the download option, it start downloading everything 
            self.download()

        if not self._check_integrity(): # funcitons used to check if the data is available or not
            raise RuntimeError('Dataset not found or corrupted.' +
                               ' You can use download=True to download it')
        downloaded_list = []# empty list
        # split is a paramter passed in the begining of the intializing of the function
        if split=='train':
            downloaded_list = self.train_list# global bariables containing the files names of training
        elif split=='test':
            downloaded_list = self.test_list # global bariables containing the files names of test
        elif split=='train+test':
            downloaded_list.extend(self.train_list)# put in a list
            downloaded_list.extend(self.test_list)# extend is just like append but it places items in begining of list
            # in here we can say that downlaoded list has the test items first then training items

        self.data = []# two empty lists
        self.targets = []# two empty lists

        # now load the picked numpy arrays
        # each item in downlaoded list contain the file name and code. I donot understand this code
        # but he is using it 
        for file_name, checksum in downloaded_list:
            file_path = os.path.join(self.root, self.base_folder, file_name)# join ./data/datasets/CIFAR/ with cifar-10-batches-py with file name
            # you get sthg like ./data/datasets/CIFAR/cifar-10-batches-py/data_batch_1
            with open(file_path, 'rb') as f:# we are opening the file 
                if sys.version_info[0] == 2:# this part is due to fact that according to version of sys
                    # we import different libraries of pickle. 
                    entry = pickle.load(f)
                else:
                    entry = pickle.load(f, encoding='latin1')# loading a pickle files 
                self.data.append(entry['data'])# open the data list and add to it this entry
                # this is a numpy array of size of 10000,3072 indicating that we have 10k pictures with size of each array 
                # 3072 
                if 'labels' in entry:
                    self.targets.extend(entry['labels'])
                else:
                    # I donot understand which kind of files have fine labels instead of labels
                    # atleast by debugging cifar 10 they all had fine labels thing 
                    #  the comment code was always here
                    #  self.targets.extend(entry['coarse_labels'])
                    self.targets.extend(entry['fine_labels'])
        # you take the data the list containing in each entry 1000,3072
        # you reshape it
        self.data = np.vstack(self.data).reshape(-1, 3, 32, 32)# when you do-1 you flatten it then you turn it to 3 by 32 by 32
        # so you remember i said that the size of 1 numpy array was (10000,3072) it is turned to (10000,3,32,32) for example
        self.data = self.data.transpose((0, 2, 3, 1))  # convert to Heght*width*color
        self._load_meta()# calling function of load meta check it it is heavily commented

        ind = [i for i in range(len(self.targets)) if self.targets[i] in target_list]
        # the ind in here is used  as following
        # for length of targets which contains the labels. it is a list
        # if targets is within targetlist(do you remember target list is where we say i want to be between class 0 to 5 )
        self.data = self.data[ind]# we are slicing the data to contain only the things in my targetlist
        self.targets = np.array(self.targets)# turning it to numpy array to slice it
        self.targets = self.targets[ind].tolist()# turning it back to list
        # in the end you have data and targets containing data and labels



    def _load_meta(self):#opening the pickle file 
        path = os.path.join(self.root, self.base_folder, self.meta['filename'])
        if not check_integrity(path, self.meta['md5']):
            raise RuntimeError('Dataset metadata file not found or corrupted.' +
                               ' You can use download=True to download it')
        with open(path, 'rb') as infile:
            if sys.version_info[0] == 2:
                data = pickle.load(infile)
            else:
                data = pickle.load(infile, encoding='latin1')# loading the data
            # {'num_cases_per_batch': 10000, 
            # 'label_names': ['airplane', 'automobile', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck'], 'num_vis': 3072}
            self.classes = data[self.meta['key']]# ['airplane', 'automobile', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck']
        self.class_to_idx = {_class: i for i, _class in enumerate(self.classes)}
        #{'airplane': 0, 'automobile': 1, 'bird': 2, 'cat': 3, 'deer': 4, 'dog': 5, 'frog': 6, 'horse': 7, 'ship': 8, 'truck': 9}       
        
        # this commented part bellow was always in the code
        #  x = self.class_to_idx
        #  sorted_x = sorted(x.items(), key=lambda kv: kv[1])
        #  print(sorted_x)

    def __getitem__(self, index):
        """
        Args:
            index (int): Index

        Returns:
            tuple: (image, target) where target is index of the target class.
        """
        img, target = self.data[index], self.targets[index]

        # doing this so that it is consistent with all other datasets
        # to return a PIL Image
        img = Image.fromarray(img)

        if self.transform is not None:
            img = self.transform(img)

        if self.target_transform is not None:
            target = self.target_transform(target)

        return img, target, index

    def __len__(self):
        return len(self.data)

    def _check_integrity(self):# used to check if the files are their in this case
        # no need to redownload stuff
        root = self.root
        for fentry in (self.train_list + self.test_list):
            filename, md5 = fentry[0], fentry[1]
            fpath = os.path.join(root, self.base_folder, filename)
            if not check_integrity(fpath, md5):
                return False
        return True

    def download(self):# download teh files 
        import tarfile

        if self._check_integrity():
            print('Files already downloaded and verified')
            return

        download_url(self.url, self.root, self.filename, self.tgz_md5)

        # extract file
        with tarfile.open(os.path.join(self.root, self.filename), "r:gz") as tar:
            tar.extractall(path=self.root)

    def __repr__(self):
        fmt_str = 'Dataset ' + self.__class__.__name__ + '\n'
        fmt_str += '    Number of datapoints: {}\n'.format(self.__len__())
        tmp = 'train' if self.train is True else 'test'
        fmt_str += '    Split: {}\n'.format(tmp)
        fmt_str += '    Root Location: {}\n'.format(self.root)
        tmp = '    Transforms (if any): '
        fmt_str += '{0}{1}\n'.format(tmp, self.transform.__repr__().replace('\n', '\n' + ' ' * len(tmp)))
        tmp = '    Target Transforms (if any): '
        fmt_str += '{0}{1}'.format(tmp, self.target_transform.__repr__().replace('\n', '\n' + ' ' * len(tmp)))
        return fmt_str


class CIFAR100(CIFAR10):
    """`CIFAR100 <https://www.cs.toronto.edu/~kriz/cifar.html>`_ Dataset.

    This is a subclass of the `CIFAR10` Dataset.
    """
    base_folder = 'cifar-100-python'
    url = "https://www.cs.toronto.edu/~kriz/cifar-100-python.tar.gz"
    filename = "cifar-100-python.tar.gz"
    tgz_md5 = 'eb9058c3a382ffc7106e4002c42a8d85'
    train_list = [
        ['train', '16019d7e3df5f24257cddd939b257f8d'],
    ]

    test_list = [
        ['test', 'f0ef6b0ae62326f3e7ffdfab6717acfc'],
    ]
    meta = {
        'filename': 'meta',
        'key': 'fine_label_names',
        #  'key': 'coarse_label_names',
        'md5': '7973b15100ade9c7d40fb424638fde48',
    }

def CIFAR10Data(root, split='train', aug=None, target_list=range(5)):# this function is called for supervised learning
    if aug==None:
        transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
        ])
    elif aug=='once':# for supervised learning
        transform = transforms.Compose([
            transforms.RandomCrop(32, padding=4),# he random cropping while padding
            transforms.RandomHorizontalFlip(),# doing random horizontal flip
            transforms.ToTensor(),# turning it to tensor
            transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
            # Normalize a tensor image with mean and standard deviation.  my question is from where did he get this values 
            # i donot get from where does he got this values ? the std one are not the same to the computed ones
        ])
        # values from mean  [0.4913725490196078, 0.4823529411764706, 0.4466666666666667] the mean is the same  but the std is different
        # values from std [0.24705882352941178, 0.24352941176470588, 0.2615686274509804] but the std is different
        # it is not important either way now. 
    elif aug=='twice':# you are using random translateion with reflect  with random hoirozntal flip
        transform = TransformTwice(transforms.Compose([
            RandomTranslateWithReflect(4),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
        ]))
    dataset = CIFAR10(root=root, split=split, transform=transform, target_list=target_list)
    return dataset
# used for supervised and autonovel
def CIFAR10Loader(root, batch_size, split='train', num_workers=2,  aug=None, shuffle=True, target_list=range(5)):# it gets called in supervised learning
    # targetlist usually contains range for num_labeled_classes. so if i am training from class 0 to 5 then i expect labels to be [0,1,2,3,4,5] VA BENE? 
    dataset = CIFAR10Data(root, split, aug,target_list)# for supervised learning augmentation augmentation is set to once
    loader = data.DataLoader(dataset, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers)
    return loader
# used with auto class discovery
def CIFAR10LoaderMix(root, batch_size, split='train',num_workers=2, aug=None, shuffle=True, labeled_list=range(5), unlabeled_list=range(5, 10), new_labels=None):
    if aug==None:
        transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
        ])
    elif aug=='once':
        transform = transforms.Compose([
            transforms.RandomCrop(32, padding=4),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
        ])
    elif aug=='twice':
        transform = TransformTwice(transforms.Compose([
            RandomTranslateWithReflect(4),# this is a function in the utils files. i think it is commented above the funciton some informaiton of what it does
            # i donot want divide so deep in understanding how it works because it is not necessarly 
            # it relects the picture . so oyu have 2 pictures notj ust 1 
            transforms.RandomHorizontalFlip(),# part of pytorch 
            transforms.ToTensor(),
            transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
        ]))# you apply this specific transformation for mix_train_loader for auto novel class discovery
        # you call the cifar10 object which is a class in here. 
    dataset_labeled = CIFAR10(root=root, split=split, transform=transform, target_list=labeled_list)# the first 5 classes
    # dataset_labeled[0] is a tuple containing 3 things
    # first it has tuple containing 2 tensor of (3,32,32) because each tuple is repeated twice with augmentation
    # second it has class label as an integer
    # third it has index of the picture
    dataset_unlabeled = CIFAR10(root=root, split=split, transform=transform, target_list=unlabeled_list)# the last 5 classes
    # so you have 2 dataset for both labeled and unlabled
    if new_labels is not None:# we can pass some specific labels i donot know why but we can
        dataset_unlabeled.targets = new_labels
    # dataset_labeled.targets has size of 25000
    # dataset_unlabeled.targets has size of 25000
    # dataset_labeled.data has size of (25000, 32, 32, 3)
    # dataset_unlabeled.data has size of (25000, 32, 32, 3)
    dataset_labeled.targets = np.concatenate((dataset_labeled.targets,dataset_unlabeled.targets))# the labels with numpy size of (50000,)
    dataset_labeled.data = np.concatenate((dataset_labeled.data,dataset_unlabeled.data),0)# numpy array of size of (50000, 32, 32, 3)
    # first half is labled and second half is unlabled
    loader = data.DataLoader(dataset_labeled, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers)
    return loader

def CIFAR10LoaderTwoStream(root, batch_size, split='train',num_workers=2, aug=None, shuffle=True, labeled_list=range(5), unlabeled_list=range(5, 10), unlabeled_batch_size=64):
    dataset_labeled = CIFAR10Data(root, split, aug, labeled_list)
    dataset_unlabeled =  CIFAR10Data(root, split, aug, unlabeled_list)
    dataset = ConcatDataset((dataset_labeled, dataset_unlabeled))
    labeled_idxs = range(len(dataset_labeled))
    unlabeled_idxs = range(len(dataset_labeled), len(dataset_labeled)+len(dataset_unlabeled))
    batch_sampler = TwoStreamBatchSampler(labeled_idxs, unlabeled_idxs, batch_size, unlabeled_batch_size)
    loader = data.DataLoader(dataset, batch_sampler=batch_sampler, num_workers=num_workers)
    loader.labeled_length = len(dataset_labeled)
    loader.unlabeled_length = len(dataset_unlabeled)
    return loader

# used for supervised learning
def CIFAR100Data(root, split='train', aug=None, target_list=range(80)):
    if aug==None:
        transform = transforms.Compose([# for test you donot do any crop or horizontal flip you enter here with test set
            transforms.ToTensor(),
            transforms.Normalize((0.507, 0.487, 0.441), (0.267, 0.256, 0.276)),
        ])
    elif aug=='once':# enter into here during supervised learning
        transform = transforms.Compose([
            transforms.RandomCrop(32, padding=4),# random crop with padding for all sides
            transforms.RandomHorizontalFlip(),# flipp
            transforms.ToTensor(),# turn to tensor
            transforms.Normalize((0.507, 0.487, 0.441), (0.267, 0.256, 0.276)),# i donot understand from where he got this values
        ])
    elif aug=='twice':
        transform = TransformTwice(transforms.Compose([
            transforms.RandomCrop(32, padding=4),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            transforms.Normalize((0.507, 0.487, 0.441), (0.267, 0.256, 0.276)),
        ]))
    dataset = CIFAR100(root=root, split=split, transform=transform, target_list=target_list)
    return dataset
# used with cifar 100 in supervised learning 
def CIFAR100Loader(root, batch_size, split='train', num_workers=2,  aug=None, shuffle=True, target_list=range(80)):
    dataset = CIFAR100Data(root, split, aug,target_list)
    loader = data.DataLoader(dataset, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers)# returns the data laoder
    return loader

def CIFAR100LoaderMix(root, batch_size, split='train',num_workers=2, aug=None, shuffle=True, labeled_list=range(80), unlabeled_list=range(90, 100)):
    dataset_labeled = CIFAR100Data(root, split, aug, labeled_list)
    dataset_unlabeled = CIFAR100Data(root, split, aug, unlabeled_list)
    dataset_labeled.targets = np.concatenate((dataset_labeled.targets,dataset_unlabeled.targets))
    dataset_labeled.data = np.concatenate((dataset_labeled.data,dataset_unlabeled.data),0)
    loader = data.DataLoader(dataset_labeled, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers)
    return loader

def CIFAR100LoaderTwoStream(root, batch_size, split='train',num_workers=2, aug=None, shuffle=True, labeled_list=range(80), unlabeled_list=range(90, 100), unlabeled_batch_size=32):
    dataset_labeled = CIFAR100Data(root, split, aug, labeled_list)
    dataset_unlabeled = CIFAR100Data(root, split, aug, unlabeled_list)
    dataset = ConcatDataset((dataset_labeled, dataset_unlabeled))
    labeled_idxs = range(len(dataset_labeled))
    unlabeled_idxs = range(len(dataset_labeled), len(dataset_labeled)+len(dataset_unlabeled))
    batch_sampler = TwoStreamBatchSampler(labeled_idxs, unlabeled_idxs, batch_size, unlabeled_batch_size)
    loader = data.DataLoader(dataset, batch_sampler=batch_sampler, num_workers=num_workers)
    loader.labeled_length = len(dataset_labeled)
    loader.unlabeled_length = len(dataset_unlabeled)
    return loader
