"""Configuração lida do ambiente.

O compose injeta DATABASE_URL apontando para o serviço `db`; os defaults aqui são os
de quem roda o uvicorn direto no host, fora do container.
"""

import os

# `localhost` no default porque dentro do compose a variável já chega apontando para o
# serviço `db` — o default só vale para o uvicorn rodando no host.
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/simulador"
)

APP_ENV = os.getenv("APP_ENV", "development")

# Em produção um processo só serve API e frontend na mesma origem: não há CORS a liberar
# e o cookie de sessão exige HTTPS (RNF03).
PRODUCAO = APP_ENV == "production"
