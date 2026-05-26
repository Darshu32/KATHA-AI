# ODA File Converter

KATHA's `dwg_importer` uses the **Open Design Alliance File Converter** to
convert `.dwg` → `.dxf` server-side, after which the existing `dxf_importer`
extracts geometry. Without this binary, DWG uploads fall back to a
"re-export as DXF" warning — the image still builds + runs, but DWG
parsing is unavailable.

## Manual install (one-time per deployment)

1. Visit <https://www.opendesign.com/guestfiles/oda_file_converter>.
2. Pick **ODA File Converter for Linux** (the **x86_64 .deb** variant for
   our Debian-based production image), accept the EULA, and download.
3. Place the resulting file in this directory **with the exact name
   pattern** the Dockerfile expects:

   ```
   backend/vendor/oda/ODAFileConverter_QT5_lnxX64_*.deb
   ```

4. Build the image. The Dockerfile detects the `.deb`, installs it
   along with the Qt/X libraries it depends on (plus `xvfb` for
   headless CLI mode), and the importer picks it up automatically via
   `app/services/oda_converter.py`.

## Why isn't this automated?

ODA's licence forbids redistribution. We cannot pull the binary from a
public URL inside the Dockerfile. The recommended deployment pattern
is to host this `.deb` in an internal artefact store (S3, GCS, Artifact
Registry) and have CI fetch it into `backend/vendor/oda/` before the
Docker build.

## Verification

After the image boots:

```bash
docker exec -it katha-backend ODAFileConverter --version
```

In Python:

```python
from app.services.oda_converter import is_available
print(is_available())  # True when installed
```

The DWG importer's response payload includes a `converter` field
(`"oda"` / `"none"` / `"oda_failed"`) that tells you live which path
ran.
