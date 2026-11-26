FROM python:3.12-slim
WORKDIR /opt/relay
COPY relay.py .
ENV RELAY_PORT=9000 RELAY_BIND=0.0.0.0
EXPOSE 9000
CMD ["python", "relay.py"]
