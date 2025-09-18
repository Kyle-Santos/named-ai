import torch
import torch.nn as nn
import torch.nn.functional as F
import math

class ArcMarginProduct(nn.Module):
    """
    Implement of ArcFace (https://arxiv.org/pdf/1801.07698v1.pdf):
    """
    def __init__(self, in_features, out_features, scale=64.0, margin=0.50, easy_margin=False):
        """
        Args:
            in_features: size of input features
            out_features: size of output features (number of classes)
            scale: norm of input feature
            margin: margin
            easy_margin: use easy margin if True
        """
        super(ArcMarginProduct, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.scale = scale
        self.margin = margin
        self.weight = nn.Parameter(torch.FloatTensor(out_features, in_features))
        nn.init.xavier_uniform_(self.weight)

        self.easy_margin = easy_margin
        self.cos_m = math.cos(margin)
        self.sin_m = math.sin(margin)
        self.th = math.cos(math.pi - margin)
        self.mm = math.sin(math.pi - margin) * margin

    def forward(self, input, label):
        # --------------------------- cos(theta) & phi(theta) ---------------------------
        cosine = F.linear(F.normalize(input), F.normalize(self.weight))
        sine = torch.sqrt(1.0 - torch.pow(cosine, 2))
        
        # phi = cosine * cos(margin) - sine * sin(margin)
        phi = cosine * self.cos_m - sine * self.sin_m
        
        if self.easy_margin:
            phi = torch.where(cosine > 0, phi, cosine)
        else:
            phi = torch.where(cosine > self.th, phi, cosine - self.mm)
        
        # --------------------------- convert label to one-hot ---------------------------
        one_hot = torch.zeros(cosine.size(), device=input.device)
        one_hot.scatter_(1, label.view(-1, 1).long(), 1)
        
        # -------------torch.where(out_i = {x_i if condition_i else y_i) -------------
        output = (one_hot * phi) + ((1.0 - one_hot) * cosine)
        output *= self.scale

        return output, cosine

class ArcFaceLoss(nn.Module):
    """
    ArcFace Loss Function
    """
    def __init__(self, in_features, out_features, scale=64.0, margin=0.50, easy_margin=False):
        super(ArcFaceLoss, self).__init__()
        self.arc_margin = ArcMarginProduct(
            in_features=in_features,
            out_features=out_features,
            scale=scale,
            margin=margin,
            easy_margin=easy_margin
        )
        self.criterion = nn.CrossEntropyLoss()

    def forward(self, features, labels):
        arc_output, cosine = self.arc_margin(features, labels)
        loss = self.criterion(arc_output, labels)
        return loss, cosine