FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app

COPY requirements.txt /app/requirements.txt
# pip (and the urllib3/msgpack/setuptools copies vendored inside it) is only
# needed to build the image, so it is uninstalled once requirements are in.
RUN pip install --no-cache-dir --upgrade "pip>=26.2" \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && pip uninstall -y pip

COPY app /app/app
COPY tests /app/tests
COPY pytest.ini /app/pytest.ini
COPY pyproject.toml /app/pyproject.toml

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host=0.0.0.0", "--port=8000"]
