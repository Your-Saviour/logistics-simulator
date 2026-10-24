FROM golang:1.26.1-alpine AS build
ENV GOMAXPROCS=2
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -p 1 -tags nomsgpack -trimpath -o /logistics .
FROM alpine:3.23.3
RUN apk add --no-cache ca-certificates tzdata && adduser -D -u 10001 logistics
COPY --from=build /logistics /usr/local/bin/logistics
USER logistics
ENV ROLE=api SIMULATOR=logistics
EXPOSE 8000
ENTRYPOINT ["logistics"]
