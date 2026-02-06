# Installation

There are two ways to install Neuro SAN depending on your use case.

## Option 1: Install as a Python Package

This is the simplest approach if you want to use Neuro SAN as a library in your own project.

```bash
python -m venv venv
source venv/bin/activate
pip install neuro-san
```

Set the `PYTHONPATH` to your project root:

```bash
export PYTHONPATH=$(pwd)
```

## Option 2: Clone from Source

Clone the repository if you want to explore examples, run tests, or contribute to the project.

```bash
git clone https://github.com/cognizant-ai-lab/neuro-san.git
cd neuro-san
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$(pwd)
```

## Verify the Installation

Set your API key and run the hello\_world agent:

```bash
export OPENAI_API_KEY="your-api-key-here"
python -m neuro_san.client.agent_cli --agent hello_world
```

Type a message when prompted:

```
From earth, I approach a new planet and wish to send a short 2-word greeting to the new orb.
```

You should see a response like:

```
Hello, world.
```

If you see a response, Neuro SAN is installed and working correctly.

## Windows Users

On Windows, use the following to activate the virtual environment:

```cmd
.\venv\Scripts\activate.bat
set PYTHONPATH=%CD%
```

## Next Steps

- [Quick Start](quickstart.md) -- Walk through building and running agent networks
- [Neuro SAN Studio](studio.md) -- Set up the full IDE with a web UI
