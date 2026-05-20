# LeHome Challenge — Policy Server Template
#
# Contestants: modify ONLY the sections marked with [CONTESTANT].
# Do not change the gRPC service interface (services_pb2*.py, protocol.py).
#
# Build:  docker build -t lehome-policy-<team> .
# Run:    docker run --rm --gpus all -p 8080:8080 lehome-policy-<team>

# [CONTESTANT] Change base image if you need a different CUDA version.
FROM python:3.12-slim

WORKDIR /app

# System deps (add libGL etc. if your model needs OpenCV display)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# [CONTESTANT] Install your model's extra dependencies here,
# or add them to requirements.txt.
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# Protocol files (do not modify)
COPY services_pb2.py        /app/
COPY services_pb2_grpc.py   /app/
COPY protocol.py            /app/

# [CONTESTANT] Copy your model weights here.
# Example:  COPY checkpoints/ /app/checkpoints/

# [CONTESTANT] Replace server.py with your implementation.
COPY server.py              /app/

COPY entrypoint.sh          /app/
RUN chmod +x /app/entrypoint.sh

EXPOSE 8080

# Environment variable defaults (override with -e when running)
ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8080
ENV SERVER_FPS=20
ENV SERVER_CHUNK=20

ENTRYPOINT ["/app/entrypoint.sh"]
