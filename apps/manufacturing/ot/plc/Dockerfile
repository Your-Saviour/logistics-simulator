FROM ghcr.io/autonomy-logic/openplc-runtime@sha256:2ca9fc611f25c3ad0471b996a4bf27507ac112612292426ca6d5ca4bf06e97e6
COPY apps/manufacturing/ot/plc/plugins.conf /workdir/plugins.conf
COPY apps/manufacturing/ot/compatibility/program_artifact.py /workdir/program_artifact.py
COPY apps/manufacturing/ot/plc/start-cell.sh /workdir/start-cell.sh
CMD ["sh", "/workdir/start-cell.sh"]
