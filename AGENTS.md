# Project Context & Agents Richtlijnen

Dit is een Home-Assistant integratie die niet meer de aandacht krijg die het
nodig heeft. Ik heb 'm nu geforkt en wil 'm bijhouden zodat ie in de toekomst
ook bruikbaar blijft. De laatste commit is van mij, de rest komt uit de
oorspronkelijke repository.

## Stack & Architectuur

- Taal/runtime: Python 3.14, tenzij een oudere versie vereist is door een bepaalde module

## Werkwijze & Commando's

- Tests draaien: `pytest -v tests/`
- Linting: `pre-commit run --all`
- Type checking: `mypy .`

## Codeerconventies

- Typehints zijn overal verplicht.
- Schrijf docstrings conform de Google-stijl.
- Houd functies klein en single-purpose.
- Codestyle forceren m.b.v. `ruff format`

## Version control

- Je mag je changes in `git` committen met een duidelijke commit message.
- Elke soort wijziging een commit, probeer te voorkomen dat er meerdere tasks/changes in 1 commit zitten.
- Behalve een `commit` doe je in `git` niks zonder mijn toestemming.
- Gebruik de Conventional Commits standaard voor commit messages.

## Beperkingen & Constraints

- Pas nooit dependencies aan in `pyproject.toml` zonder expliciete toestemming.
- Draai na elke codewijziging eerst de linter en unit tests voordat je de taak afrondt.
- Gebruik `.gitignores` files voor dezelfde doeleinden als een`.opencodeignore` file.

## Taal

- Comments, commit messages, documentatie moeten allemaal in het Engels

## Omgeving

- Linux, Debian/RaspberryPi OS
- Architectuur arm64
- De agent draait in een OCI container, als er iets mist laat het me weten
