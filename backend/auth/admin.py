"""Papel de administrador — só pela linha de comando, nunca pela interface.

    docker compose exec backend python -m auth.admin promover pessoa@exemplo.com
    docker compose exec backend python -m auth.admin rebaixar pessoa@exemplo.com

Quem tem acesso ao servidor decide quem é admin. Assim, uma falha na interface não
consegue fabricar um administrador.
"""

import asyncio
import sys

from core import db

PAPEIS = {"promover": "admin", "rebaixar": "estudante"}


async def mudar(acao: str, email: str) -> bool:
    async with db.abrir_sessao() as s:
        return await db.definir_papel(s, email, PAPEIS[acao])


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in PAPEIS:
        sys.exit(__doc__)
    acao, email = sys.argv[1:]
    if not asyncio.run(mudar(acao, email)):
        sys.exit(f"Nenhuma conta com o email {email}.")
    print(f"{email}: agora é {PAPEIS[acao]}.")
