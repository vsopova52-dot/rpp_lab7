FROM python:3.12-slim

WORKDIR /balancer

COPY balancer/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY balancer/balancer.py ./

EXPOSE 8000
CMD ["python", "balancer.py"]
