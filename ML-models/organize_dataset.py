import os
import shutil
from sklearn.model_selection import train_test_split
from typing import List, Tuple
import argparse
from tqdm import tqdm

def create_directory(path: str) -> None:
    """Create directory if it doesn't exist"""
    if not os.path.exists(path):
        os.makedirs(path)

def get_image_files(directory: str) -> List[Tuple[str, str]]:
    """Get all image files from directory with their labels (subdirectory names)"""
    image_files = []
    for label in os.listdir(directory):
        label_path = os.path.join(directory, label)
        if os.path.isdir(label_path):
            for img_name in os.listdir(label_path):
                if img_name.lower().endswith(('.png', '.jpg', '.jpeg')):
                    image_files.append((os.path.join(label_path, img_name), label))
    return image_files

def organize_dataset(
    source_dir: str,
    output_dir: str,
    train_ratio: float = 0.8,
    seed: int = 42
) -> None:
    """
    Organize dataset into train and validation splits.
    
    Args:
        source_dir: Directory containing face images organized in class folders
        output_dir: Directory to save organized dataset
        train_ratio: Ratio of images to use for training
        seed: Random seed for reproducibility
    """
    # Create output directories
    train_dir = os.path.join(output_dir, 'train')
    val_dir = os.path.join(output_dir, 'val')
    create_directory(train_dir)
    create_directory(val_dir)
    
    # Get all image files and their labels
    image_files = get_image_files(source_dir)
    if not image_files:
        print(f"No images found in {source_dir}")
        return
    
    # Split into train and validation sets
    train_files, val_files = train_test_split(
        image_files,
        train_size=train_ratio,
        random_state=seed,
        stratify=[label for _, label in image_files]
    )
    
    # Copy files to train directory
    print("Organizing training set...")
    for img_path, label in tqdm(train_files):
        dst_dir = os.path.join(train_dir, label)
        create_directory(dst_dir)
        shutil.copy2(img_path, os.path.join(dst_dir, os.path.basename(img_path)))
    
    # Copy files to validation directory
    print("Organizing validation set...")
    for img_path, label in tqdm(val_files):
        dst_dir = os.path.join(val_dir, label)
        create_directory(dst_dir)
        shutil.copy2(img_path, os.path.join(dst_dir, os.path.basename(img_path)))
    
    print(f"\nDataset organized successfully!")
    print(f"Training samples: {len(train_files)}")
    print(f"Validation samples: {len(val_files)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Organize face recognition dataset")
    parser.add_argument("--source", type=str, required=True, help="Source directory with face images")
    parser.add_argument("--output", type=str, required=True, help="Output directory for organized dataset")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Ratio of images for training (default: 0.8)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    
    args = parser.parse_args()
    organize_dataset(args.source, args.output, args.train_ratio, args.seed)