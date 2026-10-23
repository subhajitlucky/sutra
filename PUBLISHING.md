# Publishing SUTRA

- PyPI distribution: `sutra-a2a`
- Import package: `sutra_lang`
- CLI command: `sutra`

## Build and check

```bash
rm -rf dist build *.egg-info
python -m build
python -m twine check dist/*
```

## Test on TestPyPI

```bash
python -m twine upload --repository testpypi dist/*
python -m pip install --index-url https://test.pypi.org/simple/ --no-deps sutra-a2a
sutra demo
```

## Publish to PyPI

Create an API token at <https://pypi.org/manage/account/token/>, then:

```bash
python -m twine upload dist/*
```

## Version bumps

Update both `pyproject.toml` and `sutra_lang/__init__.py`, rebuild, and upload.
Never reuse a version number.
