# named-ai

A Named Networking–based protocol for distributing and executing in-network AI/ML functions.

---

## 📌 Overview

`named-ai` implements a **Named Networking (NN)**-inspired system where nodes can:
- Retrieve content via hierarchical naming
- Execute **in-network AI/ML functions**
- Forward and process requests dynamically

It supports distributed execution of image processing and face recognition pipelines across nodes.

---

## ⚙️ Requirements

- Python 3.8+
- OS: Windows or macOS (insightface is not supported)

---

### Python Dependencies

Install required libraries:

```bash
pip install -r requirements.txt
```

---

## How to Run

### Run individually

```bash
python .\node_runner.py --node /dlsu/goks/cam
python .\node_runner.py --node /dlsu/goks
python .\node_runner.py --node /dlsu
python .\node_runner.py --node /dlsu/andrew
python .\node_runner.py --node /dlsu/velasco
python .\node_runner.py --client user
```

### Run Once

Windows

```bash
python run_nodes.py
```

Mac

```bash
python mac_run_nodes.py
```

### Send an Interest Packet

#### Simple Content Retrieval
```bash
send interest /dlsu/goks/cam/capture8.jpg

send interest /3.txt

send interest /14.jpg
```

#### With In-Network Functions
```bash
send interest /dlsu/recognize(mobilefacenet(/14.jpg))

send interest /dlsu/recognize(insightface(/14.jpg))

send interest /dlsu/recognize(facenet(/14.jpg))

send interest /dlsu/andrew/grayscale(/14.jpg)

send interest /dlsu/goks/resize_mfn(/14.jpg)

send interest /dlsu/recognize(insightface(/dlsu/goks/cam/capture14.jpg))

send interest /dlsu/recognize(facenet(/dlsu/goks/cam/capture14.jpg))

send interest /dlsu/recognize(mobilefacenet(/dlsu/goks/cam/capture14.jpg))
```

---

## ML Pipeline

- get image -> detect -> grayscale (if applicable) -> resize -> normalize (if applicable) -> convert to tensor/model input -> Extract Embeddings -> Face Recognition


## ML Model Specifications

### ArcFace/InsightFace

- Minimum size of images must be 640px x 640px
- Will only accept non-grayscale images (model is trained on RGB images)
- **libraries**: insightface onnxruntime opencv-python

---

### Facenet

- Minimum size of images must be 160px x 160px
- **libraries**: facenet-pytorch mtcnn torch torchvision

---

### MobileFaceNet

- Minimum size of images must be 112px x 112px
- **libraries**: torch torchvision torchaudio
