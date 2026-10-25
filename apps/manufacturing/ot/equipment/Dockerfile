# Reuse the verified runtime's Python standard library; no pip dependencies.
FROM ghcr.io/autonomy-logic/openplc-runtime@sha256:2ca9fc611f25c3ad0471b996a4bf27507ac112612292426ca6d5ca4bf06e97e6
WORKDIR /equipment
COPY apps/manufacturing/ot/equipment/*.py ./
EXPOSE 8010
ENTRYPOINT ["python3", "server.py"]
