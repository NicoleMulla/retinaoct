# Docker rather than the gradio SDK deliberately. Under the gradio SDK the
# platform's own launcher races this app's uvicorn for the port and the Space
# dies with "address already in use". Owning the entrypoint removes that.
FROM python:3.11-slim

# Spaces run containers as a non-root user; HOME must be writable for the
# HuggingFace cache the model download uses.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    PYTHONUNBUFFERED=1 \
    PORT=7860
WORKDIR $HOME/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

EXPOSE 7860
CMD ["python", "app.py"]
