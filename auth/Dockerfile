FROM golang:1.22-alpine AS base

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .

FROM base AS check
RUN test -z "$(gofmt -l .)"
RUN go vet ./...
RUN go test ./...

FROM base AS build
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/auth ./cmd/server

FROM alpine:3.22
RUN apk add --no-cache ca-certificates tzdata && \
    addgroup -S app && adduser -S -G app app
WORKDIR /app
COPY --from=build /out/auth /usr/local/bin/auth
RUN mkdir -p /app/log && chown -R app:app /app
USER app
EXPOSE 8001
CMD ["auth"]
