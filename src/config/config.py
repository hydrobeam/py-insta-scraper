import toml
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ConfigClass:
    config_file = Path(__file__).parent / "config.toml"

    def __post_init__(self):
        self.data = toml.load(self.config_file)


config = ConfigClass()
