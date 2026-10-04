"""Offline contract syntax, specification, and reference checks. No payload output."""
import json
from pathlib import Path
import sys


def check_refs(node, document):
    if isinstance(node, dict):
        for key in ("$ref", "$dynamicRef"):
            if key not in node:
                continue
            ref = node[key]
            if not isinstance(ref, str) or (ref != "#" and not ref.startswith("#/")):
                raise ValueError("only document-local JSON Pointer references are supported")
            target = document
            if ref != "#":
                for token in ref[2:].split("/"):
                    token = token.replace("~1", "/").replace("~0", "~")
                    target = target[int(token)] if isinstance(target, list) else target[token]
        for value in node.values():
            check_refs(value, document)
    elif isinstance(node, list):
        for value in node:
            check_refs(value, document)


def validate_file(path, is_openapi):
    import yaml
    from jsonschema.validators import validator_for
    from openapi_spec_validator import validate

    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise ValueError("duplicate mapping key")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    # JSON is a YAML subset, so this also rejects duplicate keys in JSON files.
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)
    check_refs(document, document)  # Reject external refs before any validator can fetch them.
    if is_openapi:
        if not isinstance(document, dict) or not str(document.get("openapi", "")).startswith(("3.0.", "3.1.")):
            raise ValueError("OpenAPI 3.0 or 3.1 is required")
        validate(document)
    else:
        # Enforce actual JSON syntax for *.schema.json, including quoted keys.
        json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, (dict, bool)):
            raise ValueError("schema must be an object or boolean")
        validator_for(document).check_schema(document)


def main(root):
    files = []
    contract_root = root / "packages/contracts"
    if contract_root.exists():
        for path in contract_root.rglob("*"):
            if any(part in {".venv", "venv", "node_modules", "__pycache__"} for part in path.parts):
                continue
            if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}:
                files.append((path, True))
            elif path.is_file() and path.name.lower().startswith("openapi") and path.suffix.lower() == ".json":
                files.append((path, True))
            elif path.is_file() and path.name.endswith(".schema.json"):
                files.append((path, False))
    for directory in (root / "services/api", root / "services/ai"):
        if not directory.exists():
            continue
        for path in directory.rglob("*.schema.json"):
            if not any(part in {".venv", "venv", "node_modules", "__pycache__"} for part in path.parts):
                files.append((path, False))
    files = sorted(set(files), key=lambda item: str(item[0]))
    if not files:
        print("Skipping contract validation: no OpenAPI or JSON Schema files are present yet.")
        return 0
    failed = False
    for path, is_openapi in files:
        try:
            validate_file(path, is_openapi)
        except Exception as exc:
            # Validator errors can include examples or whole source snippets; never echo them.
            print(f"Contract validation failed ({type(exc).__name__}); inspect the contract locally.", file=sys.stderr)
            failed = True
    if not failed:
        print(f"Contract validation passed ({len(files)} files).")
    return int(failed)


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
