"""Build the Linux x86_64 Python 3.12 image-validation layer from a pinned wheel."""
import pathlib
import subprocess
import sys
import tempfile
import zipfile

root = pathlib.Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="image-layer-") as directory:
    subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--no-deps",
        "--platform", "manylinux_2_28_x86_64", "--python-version", "312", "--implementation", "cp", "--abi", "cp312",
        "-r", str(root / "scripts/image-requirements.txt"), "--dest", directory], check=True)
    wheel = next(pathlib.Path(directory).glob("*.whl"))
    with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(root / "infra/image_validation_layer.zip", "w", zipfile.ZIP_DEFLATED) as output:
        for entry in source.infolist():
            if not entry.is_dir():
                target = zipfile.ZipInfo("python/" + entry.filename, date_time=(2020, 1, 1, 0, 0, 0))
                target.compress_type = zipfile.ZIP_DEFLATED
                target.external_attr = 0o644 << 16
                output.writestr(target, source.read(entry))
print("Built infra/image_validation_layer.zip")
