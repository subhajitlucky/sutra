# Publishing SUTRA

- PyPI distribution: `sutra-a2a`
- Import package: `sutra_lang`
- CLI command: `sutra`

## Trusted Publishing (recommended)

Future releases can publish from GitHub without a long-lived token.

1. On PyPI, open the `sutra-a2a` project → **Publishing** → **Add a new publisher**.
2. Choose **GitHub** and set:
   - Owner: `subhajitlucky`
   - Repository: `sutra`
   - Workflow: `publish.yml`
   - Environment: leave blank
3. Publish a GitHub release. `.github/workflows/publish.yml` builds the
   distributions and uploads them with OIDC.

The manual token flow below remains available for the first release or an
emergency.

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
