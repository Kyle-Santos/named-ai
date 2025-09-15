import os
import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from PIL import Image
from typing import Optional, Callable, Tuple

class FaceDataset(Dataset):
    """Dataset for loading face images with their labels"""
    
    def __init__(
        self,
        root_dir: str,
        transform: Optional[Callable] = None,
        target_size: Tuple[int, int] = (112, 112)  # Standard size for MobileFaceNet
    ):
        """
        Args:
            root_dir: Directory with all the images organized in class folders
            transform: Optional transform to be applied on a sample
            target_size: Size to resize images to (width, height)
        """
        self.root_dir = root_dir
        self.transform = transform
        self.target_size = target_size
        
        # Get all image paths and labels
        self.samples = []
        self.class_to_idx = {}
        self.idx_to_class = {}
        
        # Create class mapping
        classes = sorted([d for d in os.listdir(root_dir) if os.path.isdir(os.path.join(root_dir, d))])
        self.class_to_idx = {cls_name: i for i, cls_name in enumerate(classes)}
        self.idx_to_class = {i: cls_name for cls_name, i in self.class_to_idx.items()}
        
        # Collect all valid image files
        for class_name in classes:
            class_dir = os.path.join(root_dir, class_name)
            if os.path.isdir(class_dir):
                for fname in os.listdir(class_dir):
                    if self._is_valid_file(fname):
                        path = os.path.join(class_dir, fname)
                        self.samples.append((path, self.class_to_idx[class_name]))
    
    def __len__(self) -> int:
        return len(self.samples)
    
    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, int]:
        """
        Args:
            idx: Index of the sample to fetch
            
        Returns:
            tuple: (image, label) where label is the class index
        """
        img_path, label = self.samples[idx]
        
        # Load and convert to RGB
        image = Image.open(img_path).convert('RGB')
        
        # Apply transformations
        if self.transform:
            image = self.transform(image)
        
        return image, label
    
    def _is_valid_file(self, filename: str) -> bool:
        """Check if a file is a valid image file"""
        return filename.lower().endswith(('.png', '.jpg', '.jpeg'))
    
    @property
    def num_classes(self) -> int:
        """Get the number of classes in the dataset"""
        return len(self.class_to_idx)

def get_data_transforms(target_size: Tuple[int, int] = (112, 112)) -> Tuple[Callable, Callable]:
    """
    Get data transformations for training and validation
    
    Args:
        target_size: Size to resize images to (width, height)
        
    Returns:
        tuple: (train_transform, val_transform)
    """
    train_transform = transforms.Compose([
        transforms.Resize(target_size),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(10),
        transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])
    
    val_transform = transforms.Compose([
        transforms.Resize(target_size),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    ])
    
    return train_transform, val_transform

def create_dataloaders(
    data_dir: str,
    batch_size: int = 32,
    num_workers: int = 4,
    target_size: Tuple[int, int] = (112, 112)
) -> Tuple[DataLoader, DataLoader, int]:
    """
    Create DataLoaders for training and validation
    
    Args:
        data_dir: Root directory containing 'train' and 'val' subdirectories
        batch_size: Batch size for training
        num_workers: Number of worker processes for data loading
        target_size: Size to resize images to (width, height)
        
    Returns:
        tuple: (train_loader, val_loader, num_classes)
    """
    train_dir = os.path.join(data_dir, 'train')
    val_dir = os.path.join(data_dir, 'val')
    
    # Get transforms
    train_transform, val_transform = get_data_transforms(target_size)
    
    # Create datasets
    train_dataset = FaceDataset(train_dir, transform=train_transform, target_size=target_size)
    val_dataset = FaceDataset(val_dir, transform=val_transform, target_size=target_size)
    
    # Create data loaders
    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=num_workers,
        pin_memory=True
    )
    
    val_loader = DataLoader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True
    )
    
    return train_loader, val_loader, train_dataset.num_classes