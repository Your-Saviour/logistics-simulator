# Evaluation image only; never imported into application images.
FROM python:3.12-slim
RUN pip install --no-cache-dir numpy==2.1.1 pandas==2.2.3 dill==0.4.0 scipy==1.15.2 openpyxl==3.1.5 cerberus==1.3.7
WORKDIR /ofact
COPY . .
ENV PYTHONPATH=/ofact
