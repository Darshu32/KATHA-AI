FROM python:3.13-slim

WORKDIR /app/backend

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Optional: ODA File Converter for native DWG → DXF in the importer.
# When backend/vendor/oda/ODAFileConverter*.deb is present, install it
# along with the Qt/X libs it needs and xvfb (the CLI mode still loads
# Qt and complains without an X server). When absent, the dwg_importer
# falls back to its actionable redirect — image still builds + runs.
# See docs/operations.md ("ODA File Converter") for the manual fetch
# step; the binary is non-redistributable per ODA's EULA so we cannot
# pull it from a public URL inside this Dockerfile.
COPY backend/vendor /tmp/vendor
RUN if ls /tmp/vendor/oda/ODAFileConverter*.deb 1>/dev/null 2>&1; then \
        apt-get update && \
        apt-get install -y --no-install-recommends \
            /tmp/vendor/oda/ODAFileConverter*.deb \
            libxcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
            libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 \
            libxcb-render0 libxcb-shape0 libxcb-shm0 libxcb-sync1 \
            libxcb-util1 libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1 \
            libxkbcommon0 libxkbcommon-x11-0 libfontconfig1 \
            libdbus-1-3 libx11-xcb1 xvfb && \
        rm -rf /var/lib/apt/lists/*; \
    fi && rm -rf /tmp/vendor

# Python deps
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code + monorepo context needed for architecture indexing
COPY backend /app/backend
COPY frontend /app/frontend
COPY packages /app/packages
COPY docs /app/docs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
