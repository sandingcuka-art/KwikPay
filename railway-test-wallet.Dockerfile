FROM maven:3.9-eclipse-temurin-21 AS java-build
WORKDIR /build
COPY pom.xml ./
COPY src ./src
RUN mvn -q -DskipTests package dependency:copy-dependencies -DincludeScope=runtime -DoutputDirectory=/build/dependencies

FROM node:22-alpine AS dashboard-build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN VITE_KWIKPAY_HOSTED=true npm run build

FROM alpine:3.20 AS apk-build
RUN apk add --no-cache zstd
WORKDIR /packages
COPY downloads ./
RUN zstd -d --patch-from=kwikpay-merchant-0.2.0.apk kwikpay-merchant-0.2.1.apk.zst -o kwikpay-merchant-0.2.1.apk
RUN zstd -d --patch-from=kwikpay-merchant-0.2.0.apk kwikpay-merchant-0.2.2.apk.zst -o kwikpay-merchant-0.2.2.apk

FROM eclipse-temurin:21-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=java-build /build/target/classes /app/classes
COPY --from=java-build /build/dependencies /app/dependencies
COPY --from=dashboard-build /web/dist /app/dashboard
COPY *.py ./
COPY migrations ./migrations
COPY --from=apk-build /packages/*.apk ./downloads/
COPY downloads/manifest.json ./downloads/manifest.json
ENV KWIKPAY_JAVA=java
ENV KWIKPAY_BRIDGE_CLASSPATH=/app/classes:/app/dependencies/*
CMD ["python3", "-u", "mobile_test_start.py"]
