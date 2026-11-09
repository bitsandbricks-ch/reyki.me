# reyki.me: the landing page plus the service list from Kubernetes. Standard library only.
FROM python:3.13-alpine
WORKDIR /app
COPY server/app.py server/app.py
COPY site/ site/
USER 10001:10001
ENV PYTHONUNBUFFERED=1 PORT=8080
EXPOSE 8080
CMD ["python", "server/app.py"]
