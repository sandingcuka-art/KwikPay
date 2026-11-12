FROM python:3.12-slim
WORKDIR /app
COPY mobile_demo_api.py payment_plan.py ./
CMD ["python", "-u", "mobile_demo_api.py"]
