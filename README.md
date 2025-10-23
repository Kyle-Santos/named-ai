# named-ai

python .\node_runner.py --node /dlsu/goks/cam

python .\node_runner.py --node /dlsu/goks

python .\node_runner.py --node /dlsu

python .\node_runner.py --client client

send interest /dlsu/goks/cam/capture8.jpg

send interest /dlsu/grayscale(/dlsu/goks/cam/capture8.jpg)

send interest /dlsu/grayscale(/dlsu/goks/detect(/dlsu/goks/cam/capture1.jpg))

send interest /dlsu/resize(grayscale(/dlsu/goks/detect(/dlsu/goks/cam/capture1.jpg)))


## ML Pipeline
get image -> detect -> grayscale (if applicable) -> resize -> normalize -> convert to tensor/model input -> Extract Embeddings -> Face Recognition


interest_name="/dlsu/goks/cam/capture8.jpg"
interest_name="/dlsu/goks/detect(/dlsu/goks/cam/capture8.jpg)"
