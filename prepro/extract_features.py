import torch.nn as nn
from torchvision import datasets, models, transforms
from torch.utils.data import DataLoader
import torch
import argparse
import numpy as np
import h5py
from PIL import Image, ImageFile
import glob
import os
import time


MODEL_DICT = {"resnet18" : models.resnet18(pretrained=True)}


class h5py_Dataset:
    def __init__(self, root_dir, transform, h5fh):
        ## change this if your storage format is different
        file_paths = sorted(glob.glob("{}/*/*/*.png".format(root_dir)))
        file_paths = [fp for fp in file_paths if os.path.isfile(fp) and fp.endswith('.png')]
        print("# FILES: {}".format(len(file_paths)))
        self.file_paths = file_paths

        self.transform = transform
        h5fh.create_dataset('file_paths', data=np.array(file_paths, dtype='S'))
        slide_ids = [fp.split('/')[-2] for fp in file_paths]
        labels = [0 if fp.split('/')[-3]=='cancer' else 1 for fp in file_paths]
        h5fh.create_dataset('slide_ids', data=np.array(slide_ids, dtype='S'))
        h5fh.create_dataset('labels', data=np.array(labels, dtype=int))
        h5fh.create_dataset('length', data=len(file_paths))
        self.h5fh = h5fh

    def __getitem__(self, idx):
        fp = self.file_paths[idx]
        slide_id = self.h5fh["slide_ids"][idx].decode()
        label = self.h5fh["labels"][idx]
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        try:
            im = Image.open(fp)
        except:
            raise Exception("File {} couldnot be read".format(fp))
        return self.transform(im), fp, slide_id, label

    def __len__(self):
        return len(self.file_paths)


class Identity(nn.Module):
    def __init__(self):
        super(Identity, self).__init__()
    def forward(self, x):
        return x


def extract_features(model, device, dataloader, batch_size, h5fh):
    model.eval()
    output = np.empty((len(dataloader.dataset), 512),dtype=np.float32)
    with torch.no_grad():
        for i, (batch,_,_,_) in enumerate(dataloader):
            batch = batch.to(device)
            out = model(batch)
            output[i*batch_size : i*batch_size+len(batch)] = out.cpu().numpy()
            if i%100==0:
                print("[INFO: {}] {}/{} Done.".format(time.strftime("%d-%b-%Y %H:%M:%S"), i*batch_size+len(batch), len(dataloader.dataset)), flush=True)
        h5fh.create_dataset('embeddings', data=output, chunks=True, compression='gzip')


def main():
    parser = argparse.ArgumentParser(description='Process args for Feature Extraction')
    parser.add_argument("--root_dir", type=str, required=True)
    parser.add_argument("--h5py_file_path", type=str, required=True)
    parser.add_argument("--batch_size", type=int, default=64)
    parser.add_argument("--imagenet_model", type=str, default="resnet18")
    parser.add_argument("--image_size", type=int, default=224)
    args = parser.parse_args()


    transform = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(args.image_size),
        transforms.ToTensor(),
        transforms.Normalize([0.596, 0.436, 0.586], [0.2066, 0.240, 0.186])
        ])

    model = MODEL_DICT[args.imagenet_model]
    model.fc = Identity()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = nn.DataParallel(model).to(device)

    if os.path.isfile(args.h5py_file_path):
        os.remove(args.h5py_file_path)

    with  h5py.File(args.h5py_file_path, 'w') as h5fh:
        dataset = h5py_Dataset(root_dir=args.root_dir, transform=transform, h5fh=h5fh)
        dataloader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False, num_workers=4)

        print("Extracting features from {} at {}".format(args.root_dir, args.h5py_file_path), flush=True)
        extract_features(model, device, dataloader, args.batch_size, h5fh)
        h5fh.close()

    print("FIN.", flush=True)


if __name__=="__main__":
    main()
