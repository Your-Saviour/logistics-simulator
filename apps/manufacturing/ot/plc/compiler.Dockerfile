FROM node@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53
WORKDIR /tmp/compiler
COPY apps/manufacturing/ot/compatibility/compiler-package-lock.json ./package-lock.json
RUN wget -q -O /tmp/strucpp.tgz https://github.com/Autonomy-Logic/STruCpp/releases/download/v0.7.0/strucpp-0.7.0.tgz && \
 echo '8d78ae92d931b87c06145520222d1491206f424c147ec66ea84653cb8b0e1be5  /tmp/strucpp.tgz' | sha256sum -c - && \
 node -e 'const fs=require("fs");fs.writeFileSync("package.json",JSON.stringify(require("./package-lock.json").packages[""]));' && \
 npm ci --ignore-scripts --no-audit --no-fund && mkdir /generated
COPY apps/manufacturing/ot/compatibility/compile.mjs /probe/compile.mjs
COPY apps/manufacturing/ot/plc/cell.st /plc/cell.st
ENV PLC_SOURCE=/plc/cell.st
CMD ["node", "/probe/compile.mjs"]
