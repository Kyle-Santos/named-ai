import torch
import torch.nn as nn
import torch.nn.functional as F

class Bottleneck(nn.Module):
    def __init__(self, inp, oup, stride, expansion_ratio):
        super(Bottleneck, self).__init__()
        self.connect = stride == 1 and inp == oup

        self.conv = nn.Sequential(
            # pw
            nn.Conv2d(inp, inp * expansion_ratio, 1, 1, 0, bias=False),
            nn.BatchNorm2d(inp * expansion_ratio),
            nn.PReLU(inp * expansion_ratio),
            # dw
            nn.Conv2d(inp * expansion_ratio, inp * expansion_ratio, 3, stride,
                     1, groups=inp * expansion_ratio, bias=False),
            nn.BatchNorm2d(inp * expansion_ratio),
            nn.PReLU(inp * expansion_ratio),
            # pw-linear
            nn.Conv2d(inp * expansion_ratio, oup, 1, 1, 0, bias=False),
            nn.BatchNorm2d(oup),
        )

    def forward(self, x):
        if self.connect:
            return x + self.conv(x)
        else:
            return self.conv(x)

class MobileFaceNet(nn.Module):
    def __init__(self, embedding_size=512):
        super(MobileFaceNet, self).__init__()
        self.conv1 = nn.Conv2d(3, 64, 3, 2, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(64)
        self.prelu1 = nn.PReLU(64)
        
        self.conv2_dw = nn.Conv2d(64, 64, 3, 1, 1, groups=64, bias=False)
        self.bn2_dw = nn.BatchNorm2d(64)
        self.prelu2_dw = nn.PReLU(64)
        
        self.conv_23 = Bottleneck(64, 64, 2, 2)
        self.conv_3 = Bottleneck(64, 64, 1, 2)
        self.conv_34 = Bottleneck(64, 128, 2, 2)
        self.conv_4 = Bottleneck(128, 128, 1, 2)
        self.conv_45 = Bottleneck(128, 128, 2, 2)
        self.conv_5 = Bottleneck(128, 128, 1, 2)
        
        self.conv6_sep = nn.Conv2d(128, 512, 1, 1, 0, bias=False)
        self.bn6_sep = nn.BatchNorm2d(512)
        self.prelu6_sep = nn.PReLU(512)
        
        self.conv6_dw = nn.Linear(512 * 7 * 7, embedding_size)
        self.bn6_dw = nn.BatchNorm1d(embedding_size)

    def forward(self, x):
        out = self.prelu1(self.bn1(self.conv1(x)))
        out = self.prelu2_dw(self.bn2_dw(self.conv2_dw(out)))
        
        out = self.conv_23(out)
        out = self.conv_3(out)
        out = self.conv_34(out)
        out = self.conv_4(out)
        out = self.conv_45(out)
        out = self.conv_5(out)
        
        out = self.prelu6_sep(self.bn6_sep(self.conv6_sep(out)))
        out = out.view(out.size(0), -1)
        feature = self.bn6_dw(self.conv6_dw(out))
        
        return F.normalize(feature, p=2, dim=1)  # L2 normalization for ArcFace