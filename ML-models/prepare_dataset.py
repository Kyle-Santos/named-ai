import os
import shutil
from PIL import Image
import numpy as np
from mtcnn import MTCNN
import torch
from torchvision import transforms
from tqdm import tqdm

def create_directory(path):
    if not os.path.exists(path):
        os.makedirs(path)

def process_face(image_path, target_size=(112, 112)):
    """Process an image by resizing it to target size"""
    try:
        # Read image
        img = Image.open(image_path).convert('RGB')
        
        # Resize to target size
        img = img.resize(target_size, Image.Resampling.LANCZOS)
        
        return img
        
    except Exception as e:
        print(f"Error processing {image_path}: {e}")
        return None

def prepare_dataset(
    source_dir,
    output_dir,
    identity_name,
    target_size=(112, 112),
    train_ratio=0.8
):
    """Prepare face dataset from source images"""
    # Create output directories
    train_dir = os.path.join(output_dir, "train", identity_name)
    val_dir = os.path.join(output_dir, "val", identity_name)
    create_directory(train_dir)
    create_directory(val_dir)
    
    # Get and process images
    image_files = [f for f in os.listdir(source_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    processed_images = []
    
    print(f"Processing images for {identity_name}...")
    for img_file in tqdm(image_files):
        src_path = os.path.join(source_dir, img_file)
        processed_img = process_face(src_path, target_size)
        if processed_img is not None:
            processed_images.append((img_file, processed_img))
    
    # Split into train/val
    num_train = int(len(processed_images) * train_ratio)
    train_images = processed_images[:num_train]
    val_images = processed_images[num_train:]
    
    # Save train images
    print(f"Saving {len(train_images)} training images...")
    for img_file, face_img in train_images:
        dst_path = os.path.join(train_dir, f"processed_{img_file}")
        face_img.save(dst_path, quality=95)
    
    # Save validation images
    print(f"Saving {len(val_images)} validation images...")
    for img_file, face_img in val_images:
        dst_path = os.path.join(val_dir, f"processed_{img_file}")
        face_img.save(dst_path, quality=95)

if __name__ == "__main__":
    # Setup paths and identities
    base_dir = r"d:\named-ai\named-ai"
    output_dir = os.path.join(base_dir, "ML-models", "dataset")
    
    # Define source directories for different identities
    identity_dirs = {
        "goks": os.path.join(base_dir, "Modules", "goks_cam_node", "captures"),
        "dlsu": os.path.join(base_dir, "Modules", "client_node"),
    }
    
    print(f"Output directory: {output_dir}")
    
    # Create output directory
    create_directory(output_dir)
    
    # Process each identity
    for identity, source_dir in identity_dirs.items():
        if os.path.exists(source_dir):
            print(f"\nPreparing dataset for {identity}...")
            prepare_dataset(source_dir, output_dir, identity)
        else:
            print(f"Warning: Source directory for {identity} does not exist: {source_dir}")
    
    print("\nDataset preparation completed!")    # Print statistics
    train_dir = os.path.join(output_dir, "train", "person1")
    val_dir = os.path.join(output_dir, "val", "person1")
    
    if os.path.exists(train_dir):
        train_images = len([f for f in os.listdir(train_dir) if f.endswith(('.jpg', '.jpeg', '.png'))])
        print(f"Training images: {train_images}")
        
    if os.path.exists(val_dir):
        val_images = len([f for f in os.listdir(val_dir) if f.endswith(('.jpg', '.jpeg', '.png'))])
        print(f"Validation images: {val_images}")