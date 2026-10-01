FROM python:3.12-slim-bookworm
ARG USER_UID=1000
ARG USER_GID=1000
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g "$USER_GID" app && useradd -m -u "$USER_UID" -g app app
WORKDIR /opt/agent-rules
COPY requirements-gui.txt ./
RUN pip install --no-cache-dir -r requirements-gui.txt
COPY scripts/ scripts/
COPY templates/ templates/
COPY rules/ rules/
COPY skills/ skills/
ARG SOURCE_COMMIT
RUN printf '%s' "$SOURCE_COMMIT" | grep -Eq '^[0-9a-f]{40}$' \
    && printf '%s\n' "$SOURCE_COMMIT" > .source-commit \
    && mkdir -p /workspace && chown app:app /workspace
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    AGENT_RULES_BRIDGE_FILE=/run/secrets/ai-bridge-token
USER app
EXPOSE 8765
CMD ["python", "scripts/gui.py", "--workspace", "/workspace", "--container"]
