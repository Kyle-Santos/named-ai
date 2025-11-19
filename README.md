# named-ai

python .\node_runner.py --node /dlsu/goks/cam

python .\node_runner.py --node /dlsu/goks

python .\node_runner.py --node /dlsu

python .\node_runner.py --node /dlsu/andrew

python .\node_runner.py --node /dlsu/velasco

python .\node_runner.py --client user

send interest /dlsu/goks/cam/capture8.jpg

send interest /dlsu/grayscale(/dlsu/goks/cam/capture8.jpg)

send interest /dlsu/grayscale(/dlsu/goks/detect(/dlsu/goks/cam/capture1.jpg))

send interest /dlsu/goks/resize(detect(/dlsu/goks/cam/capture8.jpg))

send interest /dlsu/andrew/grayscale(/dlsu/goks/resize(detect(/dlsu/goks/cam/capture1.jpg)))

send interest /dlsu/velasco/normalize(/dlsu/andrew/grayscale(/dlsu/goks/resize(detect(/dlsu/goks/cam/capture1.jpg))))


send interest /dlsu/recognize(insightface(/dlsu/goks/cam/capture11.jpg))
send interest /dlsu/recognize(facenet(/dlsu/goks/cam/capture11.jpg))
send interest /dlsu/recognize(mobilefacenet(/dlsu/goks/cam/capture11.jpg))


## ML Pipeline
get image -> detect -> grayscale (if applicable) -> resize -> normalize -> convert to tensor/model input -> Extract Embeddings -> Face Recognition


interest_name="/dlsu/goks/cam/capture8.jpg"
interest_name="/dlsu/goks/detect(/dlsu/goks/cam/capture8.jpg)"


## ML Model Specifications
### ArcFace/InsightFace
Minimum size of images must be 512px x 512px 

Will only accept non-grayscale images (model is trained on RGB images)
