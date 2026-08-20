from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from typing import Any


def find_project_root(start: Path | None = None) -> Path:
    """Находит корень проекта по pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise FileNotFoundError("Не найден корень проекта с pyproject.toml.")


def sha256_bytes(data: bytes) -> str:
    """Возвращает SHA-256 набора байтов."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    """Вычисляет SHA-256 файла блоками."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_text_payload(value: Any) -> str:
    """Нормализует текстовый payload Jupyter output."""
    if isinstance(value, list):
        return "".join(str(part) for part in value)
    return str(value)


def extract_notebook_figures(
    notebook_path: Path,
    output_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    """Извлекает embedded PNG/JPEG/SVG outputs без повторного запуска notebook."""
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    target_dir = output_root / notebook_path.stem
    target_dir.mkdir(parents=True, exist_ok=True)

    mime_map = {
        "image/png": ("png", True),
        "image/jpeg": ("jpg", True),
        "image/svg+xml": ("svg", False),
    }

    files: list[dict[str, Any]] = []

    for cell_index, cell in enumerate(notebook.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue

        for output_index, output in enumerate(cell.get("outputs", [])):
            data = output.get("data")
            if not isinstance(data, dict):
                continue

            for mime_type, (extension, is_base64) in mime_map.items():
                if mime_type not in data:
                    continue

                payload = data[mime_type]
                if is_base64:
                    encoded = normalize_text_payload(payload).encode("ascii")
                    content = base64.b64decode(encoded)
                else:
                    content = normalize_text_payload(payload).encode("utf-8")

                filename = (
                    f"cell_{cell_index:02d}_output_{output_index:02d}.{extension}"
                )
                output_path = target_dir / filename
                output_path.write_bytes(content)

                files.append(
                    {
                        "cell_index": cell_index,
                        "output_index": output_index,
                        "mime_type": mime_type,
                        "path": output_path.relative_to(project_root).as_posix(),
                        "sha256": sha256_bytes(content),
                        "size_bytes": len(content),
                    }
                )

    manifest = {
        "source_notebook": notebook_path.relative_to(project_root).as_posix(),
        "source_notebook_sha256": sha256_file(notebook_path),
        "figure_count": len(files),
        "figures": files,
    }

    manifest_path = target_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Извлечь embedded графики из Jupyter notebooks в reports/figures "
            "без повторного выполнения вычислений."
        )
    )
    parser.add_argument(
        "notebooks",
        nargs="*",
        type=Path,
        help=(
            "Пути к notebook. Если не указаны, обрабатываются notebooks/*.ipynb "
            "в корне исследовательской папки."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = find_project_root()
    output_root = root / "reports" / "figures"

    if args.notebooks:
        notebook_paths = [
            path if path.is_absolute() else root / path
            for path in args.notebooks
        ]
    else:
        notebook_paths = sorted((root / "notebooks").glob("*.ipynb"))

    if not notebook_paths:
        raise FileNotFoundError("Не найдено notebook для извлечения графиков.")

    total = 0
    for notebook_path in notebook_paths:
        if not notebook_path.exists():
            raise FileNotFoundError(f"Notebook не найден: {notebook_path}")

        manifest = extract_notebook_figures(notebook_path, output_root, root)
        total += manifest["figure_count"]
        print(
            f"{notebook_path.name}: извлечено "
            f"{manifest['figure_count']} figure outputs."
        )

    print(f"Готово. Всего извлечено figure outputs: {total}")
    print(f"Каталог: {output_root}")


if __name__ == "__main__":
    main()
