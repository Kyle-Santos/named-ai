import os
import argparse
import torch
from dataset import create_dataloaders
from train import FaceRecognitionTrainer
import logging

def setup_logging(log_dir: str) -> None:
    """Set up logging configuration"""
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(os.path.join(log_dir, 'training.log')),
            logging.StreamHandler()
        ]
    )

def main():
    parser = argparse.ArgumentParser(description='Train Face Recognition Model with ArcFace')
    parser.add_argument('--data-dir', type=str, required=True,
                        help='Directory containing train and val subdirectories')
    parser.add_argument('--checkpoint-dir', type=str, default='checkpoints',
                        help='Directory to save model checkpoints')
    parser.add_argument('--log-dir', type=str, default='logs',
                        help='Directory to save training logs')
    parser.add_argument('--batch-size', type=int, default=32,
                        help='Batch size for training')
    parser.add_argument('--epochs', type=int, default=50,
                        help='Number of epochs to train')
    parser.add_argument('--lr', type=float, default=0.1,
                        help='Initial learning rate')
    parser.add_argument('--embedding-size', type=int, default=512,
                        help='Size of face embedding')
    parser.add_argument('--num-workers', type=int, default=4,
                        help='Number of data loading workers')
    parser.add_argument('--resume', type=str, default=None,
                        help='Path to checkpoint to resume from')
    
    args = parser.parse_args()
    
    # Set up logging
    setup_logging(args.log_dir)
    
    # Create checkpoint directory
    os.makedirs(args.checkpoint_dir, exist_ok=True)
    
    # Set device
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    logging.info(f'Using device: {device}')
    
    # Create data loaders
    logging.info('Creating data loaders...')
    train_loader, val_loader, num_classes = create_dataloaders(
        args.data_dir,
        batch_size=args.batch_size,
        num_workers=args.num_workers
    )
    logging.info(f'Number of classes: {num_classes}')
    
    # Initialize trainer
    trainer = FaceRecognitionTrainer(
        num_classes=num_classes,
        embedding_size=args.embedding_size,
        device=device,
        learning_rate=args.lr
    )
    
    # Resume from checkpoint if specified
    start_epoch = 0
    if args.resume:
        if os.path.isfile(args.resume):
            logging.info(f'Loading checkpoint from {args.resume}')
            start_epoch, best_acc = trainer.load_checkpoint(args.resume)
            logging.info(f'Resumed from epoch {start_epoch} with accuracy {best_acc:.2f}%')
        else:
            logging.error(f'No checkpoint found at {args.resume}')
            return
    
    # Train the model
    logging.info('Starting training...')
    trainer.train(
        train_loader=train_loader,
        val_loader=val_loader,
        epochs=args.epochs,
        checkpoint_dir=args.checkpoint_dir
    )
    
    logging.info('Training completed!')

if __name__ == '__main__':
    main()