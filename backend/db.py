"""Persistência em SQLite (stdlib) — usuários, sessões de auth, conversas e mensagens.

ponytail: conexão única com lock global serve para o protótipo; o TCC troca por
pool/Postgres se precisar de concorrência real.
"""

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_CAMINHO = Path(__file__).parent / "dados.db"
_lock = threading.Lock()
_con: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id         INTEGER PRIMARY KEY,
    nome       TEXT NOT NULL,
    email      TEXT NOT NULL UNIQUE,
    senha_hash BLOB NOT NULL,
    criado_em  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessoes (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    expira_em  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversas (
    id            TEXT PRIMARY KEY,
    usuario_id    INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    titulo        TEXT NOT NULL,
    especialidade TEXT NOT NULL,
    dificuldade   TEXT NOT NULL,
    gabarito      TEXT NOT NULL,            -- JSON; nunca enviado ao cliente antes do fim
    status        TEXT NOT NULL DEFAULT 'aberta',  -- aberta | encerrada
    feedback      TEXT,                     -- JSON, preenchido ao encerrar
    criada_em     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mensagens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    conversa_id TEXT NOT NULL REFERENCES conversas(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,              -- user | assistant
    content     TEXT NOT NULL,
    criada_em   TEXT NOT NULL
);
"""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(caminho: str | Path = _CAMINHO) -> None:
    global _con
    _con = sqlite3.connect(caminho, check_same_thread=False)
    _con.row_factory = sqlite3.Row
    _con.execute("PRAGMA foreign_keys = ON")
    _con.executescript(_SCHEMA)
    _con.commit()


def _exec(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    assert _con is not None, "init_db() não foi chamado"
    with _lock:
        cur = _con.execute(sql, params)
        _con.commit()
        return cur


# --- usuários e sessões de autenticação ---


def criar_usuario(nome: str, email: str, senha_hash: bytes) -> int:
    cur = _exec(
        "INSERT INTO usuarios (nome, email, senha_hash, criado_em) VALUES (?, ?, ?, ?)",
        (nome, email.lower(), senha_hash, _agora()),
    )
    return cur.lastrowid


def buscar_usuario_por_email(email: str) -> sqlite3.Row | None:
    return _exec("SELECT * FROM usuarios WHERE email = ?", (email.lower(),)).fetchone()


def criar_sessao(token_hash: str, usuario_id: int, dias_validade: int = 7) -> None:
    expira = (datetime.now(timezone.utc) + timedelta(days=dias_validade)).isoformat()
    _exec(
        "INSERT INTO sessoes (token_hash, usuario_id, expira_em) VALUES (?, ?, ?)",
        (token_hash, usuario_id, expira),
    )


def usuario_da_sessao(token_hash: str) -> sqlite3.Row | None:
    """Retorna o usuário da sessão válida, ou None (sessões expiradas são apagadas)."""
    linha = _exec(
        """SELECT u.*, s.expira_em FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id
           WHERE s.token_hash = ?""",
        (token_hash,),
    ).fetchone()
    if linha is None:
        return None
    if datetime.fromisoformat(linha["expira_em"]) < datetime.now(timezone.utc):
        apagar_sessao(token_hash)
        return None
    return linha


def apagar_sessao(token_hash: str) -> None:
    _exec("DELETE FROM sessoes WHERE token_hash = ?", (token_hash,))


# --- conversas e mensagens ---


def criar_conversa(
    usuario_id: int, titulo: str, especialidade: str, dificuldade: str, gabarito: dict
) -> str:
    conversa_id = uuid.uuid4().hex
    _exec(
        """INSERT INTO conversas (id, usuario_id, titulo, especialidade, dificuldade,
           gabarito, criada_em) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            conversa_id,
            usuario_id,
            titulo,
            especialidade,
            dificuldade,
            json.dumps(gabarito, ensure_ascii=False),
            _agora(),
        ),
    )
    return conversa_id


def listar_conversas(usuario_id: int) -> list[dict]:
    linhas = _exec(
        """SELECT id, titulo, especialidade, status, criada_em FROM conversas
           WHERE usuario_id = ? ORDER BY criada_em DESC""",
        (usuario_id,),
    ).fetchall()
    return [dict(l) for l in linhas]


def carregar_conversa(conversa_id: str, usuario_id: int) -> dict | None:
    """Conversa completa (com mensagens) se pertencer ao usuário; senão None."""
    conversa = _exec(
        "SELECT * FROM conversas WHERE id = ? AND usuario_id = ?",
        (conversa_id, usuario_id),
    ).fetchone()
    if conversa is None:
        return None
    mensagens = _exec(
        "SELECT role, content FROM mensagens WHERE conversa_id = ? ORDER BY id",
        (conversa_id,),
    ).fetchall()
    resultado = dict(conversa)
    resultado["gabarito"] = json.loads(resultado["gabarito"])
    resultado["feedback"] = json.loads(resultado["feedback"]) if resultado["feedback"] else None
    resultado["mensagens"] = [dict(m) for m in mensagens]
    return resultado


def adicionar_mensagem(conversa_id: str, role: str, content: str) -> None:
    _exec(
        "INSERT INTO mensagens (conversa_id, role, content, criada_em) VALUES (?, ?, ?, ?)",
        (conversa_id, role, content, _agora()),
    )


def encerrar_conversa(conversa_id: str, feedback: dict) -> None:
    _exec(
        "UPDATE conversas SET status = 'encerrada', feedback = ? WHERE id = ?",
        (json.dumps(feedback, ensure_ascii=False), conversa_id),
    )


def apagar_conversa(conversa_id: str, usuario_id: int) -> bool:
    cur = _exec(
        "DELETE FROM conversas WHERE id = ? AND usuario_id = ?", (conversa_id, usuario_id)
    )
    return cur.rowcount > 0


if __name__ == "__main__":
    # Self-check determinístico em banco na memória (sem rede, sem arquivo).
    init_db(":memory:")

    uid = criar_usuario("Teste", "Teste@Exemplo.com", b"hash-falso")
    assert buscar_usuario_por_email("teste@exemplo.com")["id"] == uid, "email case-insensitive"

    criar_sessao("tok1", uid)
    assert usuario_da_sessao("tok1")["id"] == uid
    assert usuario_da_sessao("inexistente") is None
    apagar_sessao("tok1")
    assert usuario_da_sessao("tok1") is None, "logout revoga a sessão"

    cid = criar_conversa(uid, "Dispneia aos esforços", "Cardiologia", "básico", {"d": "IC"})
    adicionar_mensagem(cid, "assistant", "Apresentação do caso")
    adicionar_mensagem(cid, "user", "Peço um ECG")
    conversa = carregar_conversa(cid, uid)
    assert conversa["gabarito"] == {"d": "IC"} and len(conversa["mensagens"]) == 2
    assert conversa["status"] == "aberta" and conversa["feedback"] is None
    assert carregar_conversa(cid, usuario_id=999) is None, "não vaza conversa de outro usuário"

    encerrar_conversa(cid, {"acertou": True})
    conversa = carregar_conversa(cid, uid)
    assert conversa["status"] == "encerrada" and conversa["feedback"] == {"acertou": True}

    assert [c["id"] for c in listar_conversas(uid)] == [cid]
    assert apagar_conversa(cid, uid) and listar_conversas(uid) == []
    assert not apagar_conversa(cid, uid), "apagar de novo retorna False"

    print("OK: CRUD de usuários, sessões, conversas e mensagens passa.")
