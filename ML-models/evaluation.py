import torch
import numpy as np
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, Tuple, List
import logging
import os

class FaceRecognitionEvaluator:
    def __init__(self, model, device='cuda' if torch.cuda.is_available() else 'cpu'):
        """
        Initialize the evaluator
        
        Args:
            model: The face recognition model to evaluate
            device: Device to run evaluation on
        """
        self.model = model
        self.device = device
        self.metrics_history = {
            'train_loss': [],
            'train_acc': [],
            'val_loss': [],
            'val_acc': [],
            'val_precision': [],
            'val_recall': [],
            'val_f1': []
        }
    
    def compute_metrics(self, labels: torch.Tensor, predictions: torch.Tensor) -> Dict[str, float]:
        """
        Compute classification metrics
        
        Args:
            labels: Ground truth labels
            predictions: Model predictions
            
        Returns:
            Dictionary containing accuracy, precision, recall, and F1 score
        """
        # Convert to numpy arrays
        labels = labels.cpu().numpy()
        predictions = predictions.cpu().numpy()
        
        # Calculate metrics
        accuracy = accuracy_score(labels, predictions)
        precision, recall, f1, _ = precision_recall_fscore_support(
            labels, predictions, average='weighted'
        )
        
        return {
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'f1': f1
        }
    
    def visualize_embeddings(
        self,
        embeddings: torch.Tensor,
        labels: torch.Tensor,
        epoch: int,
        output_dir: str
    ) -> None:
        """
        Visualize face embeddings using t-SNE
        
        Args:
            embeddings: Face embeddings from the model
            labels: Corresponding class labels
            epoch: Current epoch number
            output_dir: Directory to save the visualization
        """
        # Convert to numpy arrays
        embeddings = embeddings.cpu().numpy()
        labels = labels.cpu().numpy()
        
        # Apply t-SNE
        tsne = TSNE(n_components=2, random_state=42)
        embeddings_2d = tsne.fit_transform(embeddings)
        
        # Create scatter plot
        plt.figure(figsize=(10, 10))
        scatter = plt.scatter(
            embeddings_2d[:, 0],
            embeddings_2d[:, 1],
            c=labels,
            cmap='tab20'
        )
        plt.colorbar(scatter)
        plt.title(f'Face Embeddings Visualization (Epoch {epoch})')
        plt.xlabel('t-SNE Dimension 1')
        plt.ylabel('t-SNE Dimension 2')
        
        # Save plot
        os.makedirs(output_dir, exist_ok=True)
        plt.savefig(os.path.join(output_dir, f'embeddings_epoch_{epoch}.png'))
        plt.close()
    
    def plot_training_curves(self, output_dir: str) -> None:
        """
        Plot training and validation curves
        
        Args:
            output_dir: Directory to save the plots
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # Loss curve
        plt.figure(figsize=(10, 5))
        plt.plot(self.metrics_history['train_loss'], label='Training Loss')
        plt.plot(self.metrics_history['val_loss'], label='Validation Loss')
        plt.title('Training and Validation Loss')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.legend()
        plt.savefig(os.path.join(output_dir, 'loss_curve.png'))
        plt.close()
        
        # Accuracy curve
        plt.figure(figsize=(10, 5))
        plt.plot(self.metrics_history['train_acc'], label='Training Accuracy')
        plt.plot(self.metrics_history['val_acc'], label='Validation Accuracy')
        plt.title('Training and Validation Accuracy')
        plt.xlabel('Epoch')
        plt.ylabel('Accuracy')
        plt.legend()
        plt.savefig(os.path.join(output_dir, 'accuracy_curve.png'))
        plt.close()
        
        # Precision, Recall, F1 curves
        plt.figure(figsize=(10, 5))
        plt.plot(self.metrics_history['val_precision'], label='Precision')
        plt.plot(self.metrics_history['val_recall'], label='Recall')
        plt.plot(self.metrics_history['val_f1'], label='F1 Score')
        plt.title('Validation Metrics')
        plt.xlabel('Epoch')
        plt.ylabel('Score')
        plt.legend()
        plt.savefig(os.path.join(output_dir, 'metrics_curve.png'))
        plt.close()
    
    def update_metrics(self, metrics: Dict[str, float], phase: str) -> None:
        """
        Update metrics history
        
        Args:
            metrics: Dictionary containing metric values
            phase: 'train' or 'val'
        """
        for metric_name, value in metrics.items():
            key = f'{phase}_{metric_name}'
            if key in self.metrics_history:
                self.metrics_history[key].append(value)
    
    def log_metrics(self, epoch: int, metrics: Dict[str, float], phase: str) -> None:
        """
        Log metrics for current epoch
        
        Args:
            epoch: Current epoch number
            metrics: Dictionary containing metric values
            phase: 'train' or 'val'
        """
        msg = f'Epoch {epoch} - {phase.capitalize()}: '
        msg += ' | '.join([f'{k}: {v:.4f}' for k, v in metrics.items()])
        logging.info(msg)
    
    def evaluate_epoch(
        self,
        dataloader: torch.utils.data.DataLoader,
        criterion: torch.nn.Module,
        epoch: int,
        phase: str,
        output_dir: str
    ) -> Tuple[float, Dict[str, float]]:
        """
        Evaluate model for one epoch
        
        Args:
            dataloader: DataLoader for evaluation
            criterion: Loss function
            epoch: Current epoch number
            phase: 'train' or 'val'
            output_dir: Directory to save visualizations
            
        Returns:
            Tuple of (average loss, metrics dictionary)
        """
        self.model.eval()
        total_loss = 0
        all_labels = []
        all_preds = []
        all_embeddings = []
        
        with torch.no_grad():
            for inputs, labels in dataloader:
                inputs = inputs.to(self.device)
                labels = labels.to(self.device)
                
                # Get embeddings and predictions
                embeddings = self.model(inputs)
                loss, outputs = criterion(embeddings, labels)
                
                _, predictions = outputs.max(1)
                
                total_loss += loss.item()
                all_labels.extend(labels.cpu())
                all_preds.extend(predictions.cpu())
                all_embeddings.append(embeddings.cpu())
        
        # Calculate average loss
        avg_loss = total_loss / len(dataloader)
        
        # Convert lists to tensors
        all_labels = torch.stack(all_labels)
        all_preds = torch.stack(all_preds)
        all_embeddings = torch.cat(all_embeddings)
        
        # Compute metrics
        metrics = self.compute_metrics(all_labels, all_preds)
        metrics['loss'] = avg_loss
        
        # Update and log metrics
        self.update_metrics(metrics, phase)
        self.log_metrics(epoch, metrics, phase)
        
        # Visualize embeddings for validation set
        if phase == 'val':
            self.visualize_embeddings(all_embeddings, all_labels, epoch, output_dir)
        
        return avg_loss, metrics