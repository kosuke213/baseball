import pytest
from baseball_simulation_lab.engine import Game
from baseball_simulation_lab.generation import generate_world


@pytest.fixture
def teams():
    return generate_world(2026)


@pytest.fixture
def game(teams):
    return Game(*teams, seed=42)
