import torch
from torch.utils.data import DataLoader
import torch.optim as optim
from torch.optim.lr_scheduler import StepLR
import numpy as np
from tqdm import tqdm
import os
import logging
from datetime import datetime

from arcface import ArcFaceLoss
from mobilefacenet import MobileFaceNet
from evaluation import FaceRecognitionEvaluator

class FaceRecognitionTrainer:
    def __init__(
        self,
        num_classes,
        embedding_size=512,
        device='cuda' if torch.cuda.is_available() else 'cpu',
        learning_rate=0.1,
        momentum=0.9,
        weight_decay=5e-4
    ):
        self.device = device
        self.model = MobileFaceNet(embedding_size=embedding_size).to(device)
        self.criterion = ArcFaceLoss(
            in_features=embedding_size,
            out_features=num_classes,
            scale=64.0,
            margin=0.5,
            easy_margin=False
        ).to(device)
        
        self.optimizer = optim.SGD(
            [{'params': self.model.parameters()},
             {'params': self.criterion.parameters()}],
            lr=learning_rate,
            momentum=momentum,
            weight_decay=weight_decay
        )
        self.scheduler = StepLR(self.optimizer, step_size=10, gamma=0.1)

    def train_epoch(self, train_loader, evaluator, epoch):
        self.model.train()
        total_loss = 0
        correct = 0
        total = 0

        for batch_idx, (inputs, targets) in enumerate(tqdm(train_loader)):
            inputs, targets = inputs.to(self.device), targets.to(self.device)
            
            self.optimizer.zero_grad()
            features = self.model(inputs)
            loss, outputs = self.criterion(features, targets)
            
            loss.backward()
            self.optimizer.step()
            
            total_loss += loss.item()
            
            _, predicted = outputs.max(1)
            total += targets.size(0)
            correct += predicted.eq(targets).sum().item()
            
            # Log progress
            if (batch_idx + 1) % 10 == 0:
                logging.info(f'Train Epoch: {epoch} [{batch_idx + 1}/{len(train_loader)}]\t'
                           f'Loss: {loss.item():.6f}')

        accuracy = 100. * correct / total
        avg_loss = total_loss / len(train_loader)
        
        metrics = {
            'loss': avg_loss,
            'accuracy': accuracy
        }
        
        evaluator.update_metrics(metrics, 'train')
        evaluator.log_metrics(epoch, metrics, 'train')
        
        return avg_loss, metrics

    def validate(self, val_loader, evaluator, epoch, output_dir):
        self.model.eval()
        return evaluator.evaluate_epoch(
            dataloader=val_loader,
            criterion=self.criterion,
            epoch=epoch,
            phase='val',
            output_dir=output_dir
        )

    def train(self, train_loader, val_loader, epochs, checkpoint_dir='checkpoints', log_dir='logs'):
        # Setup directories
        os.makedirs(checkpoint_dir, exist_ok=True)
        os.makedirs(log_dir, exist_ok=True)
        
        # Setup logging
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = os.path.join(log_dir, f'training_{timestamp}.log')
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        
        # Initialize evaluator
        evaluator = FaceRecognitionEvaluator(self.model, self.device)
        best_acc = 0

        for epoch in range(epochs):
            # Training phase
            train_loss, train_metrics = self.train_epoch(train_loader, evaluator, epoch)
            
            # Validation phase
            val_loss, val_metrics = self.validate(val_loader, evaluator, epoch, log_dir)
            
            # Update learning rate
            self.scheduler.step()
            
            # Save checkpoint if validation accuracy improves
            if val_metrics['accuracy'] > best_acc:
                logging.info(f'Validation Accuracy improved from {best_acc:.3f} to {val_metrics["accuracy"]:.3f}')
                best_acc = val_metrics['accuracy']
                
                torch.save({
                    'epoch': epoch,
                    'model_state_dict': self.model.state_dict(),
                    'criterion_state_dict': self.criterion.state_dict(),
                    'optimizer_state_dict': self.optimizer.state_dict(),
                    'scheduler_state_dict': self.scheduler.state_dict(),
                    'best_acc': best_acc,
                    'metrics_history': evaluator.metrics_history
                }, os.path.join(checkpoint_dir, f'best_model_{timestamp}.pth'))
            
            # Plot training curves
            evaluator.plot_training_curves(log_dir)
            
        # Final evaluation summary
        logging.info('\nTraining completed!')
        logging.info(f'Best validation accuracy: {best_acc:.3f}')
        
        return evaluator.metrics_history

    def extract_features(self, loader):
        """Extract features for all images in the loader"""
        self.model.eval()
        features = []
        targets = []
        
        with torch.no_grad():
            for inputs, labels in loader:
                inputs = inputs.to(self.device)
                features.append(self.model(inputs).cpu().numpy())
                targets.append(labels.numpy())
                
        return np.vstack(features), np.hstack(targets)

    def load_checkpoint(self, checkpoint_path):
        """Load a saved checkpoint"""
        checkpoint = torch.load(checkpoint_path, map_location=self.device)
        self.model.load_state_dict(checkpoint['model_state_dict'])
        self.criterion.load_state_dict(checkpoint['criterion_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        self.scheduler.load_state_dict(checkpoint['scheduler_state_dict'])
        return checkpoint['epoch'], checkpoint['best_acc']