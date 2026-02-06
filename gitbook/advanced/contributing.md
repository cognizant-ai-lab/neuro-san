# Contributing

Guidelines for contributing to the Neuro SAN project.

## Development Setup

### Clone and Install

```bash
git clone https://github.com/cognizant-ai-lab/neuro-san.git
cd neuro-san
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-build.txt
export PYTHONPATH=$(pwd)
```

### For Neuro SAN Studio

```bash
git clone https://github.com/cognizant-ai-lab/neuro-san-studio.git
cd neuro-san-studio
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$(pwd)
```

## Code Standards

### Linting

Run linters before submitting:

```bash
# neuro-san
flake8 neuro_san
pylint neuro_san

# neuro-san-studio
make lint-check
```

### Testing

Run the test suite:

```bash
# neuro-san
pytest

# neuro-san-studio
make test
```

### Git Commit Messages

Follow the [seven rules of great commit messages](https://cbea.ms/git-commit/#seven-rules):

1. Separate subject from body with a blank line
2. Limit subject line to 50 characters
3. Capitalize the subject line
4. Do not end the subject line with a period
5. Use imperative mood in the subject line
6. Wrap the body at 72 characters
7. Use the body to explain what and why vs. how

## Contribution Workflow

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run linting and tests
5. Submit a pull request
6. Address review feedback

## Adding a New Agent Network

When adding a new agent network to Studio:

1. Create the HOCON file in the appropriate `registries/` subdirectory
2. Add the manifest entry
3. If it needs CodedTools, add them to `coded_tools/`
4. Add integration test fixtures in `tests/fixtures/`
5. Update the examples documentation if applicable
6. Run the HOCON validator: `python -m neuro_san.client.hocon_validator_cli --verbose`

## Reorganizing Agent Networks

When reorganizing agent networks into different directories:

1. Move the HOCON file to the new location
2. Update all manifest entries
3. Update any `coded_tool` paths that reference the old location
4. Update test fixture paths
5. Run tests to verify nothing broke
6. Update documentation references

## Next Steps

- [Extending the Framework](extending.md) -- Add new capabilities
- [Architecture Overview](architecture.md) -- Understand the internals
