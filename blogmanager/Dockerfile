FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn python-slugify jinja2 httpx
COPY main.py .
COPY templates/ templates/
RUN mkdir -p data
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]