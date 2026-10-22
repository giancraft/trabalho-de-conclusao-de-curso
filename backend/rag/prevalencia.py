"""Insumos brasileiros da dificuldade dos casos — script offline (DATASUS).

    # No host, não no container: o datasus-dbc não tem wheel para a imagem (compila Rust).
    uv run --no-project --with datasus-dbc==0.1.3 python -m rag.prevalencia   # ~6 min
    python -m rag.prevalencia --check  # self-check das faixas CID e do DBF, sem rede

- `prevalencia_sih.csv`: internações no SUS por categoria CID-10 (3 caracteres) nos 12
  meses mais recentes com todas as UFs publicadas — microdados RD do SIH/SUS.
- `icsap.csv`: Condições Sensíveis à Atenção Primária (Portaria SAS/MS nº 221/2008),
  como faixas CID-10, tiradas da tabela de conversão oficial do TabWin (TAB_SIH).

Ambos são versionados: `rag.catalogo` os lê sem rede, e a banca vê o dado que decidiu
cada dificuldade.
"""

import collections
import csv
import io
import re
import struct
import sys
import tempfile
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PREVALENCIA_CSV = RAIZ / "prevalencia_sih.csv"
ICSAP_CSV = RAIZ / "icsap.csv"

FTP = "ftp://ftp.datasus.gov.br/dissemin/publicos/SIHSUS/200801_/"
UFS = 27
MESES = 12  # um ano inteiro: sazonalidade (dengue, bronquiolite) não distorce a contagem


def _baixar(url: str) -> bytes:
    for tentativa in range(4):  # o FTP do DATASUS derruba conexões sob carga
        try:
            with urllib.request.urlopen(url, timeout=300) as resp:
                return resp.read()
        except OSError:  # URLError, reset, timeout
            if tentativa == 3:
                raise
            time.sleep(5 * (tentativa + 1))


# --- ICSAP ---


def faixas(codigos: str) -> list[tuple[str, str]]:
    """'A15 -A159,A171-A179,G000' → [('A150','A159'), ('A171','A179'), ('G000','G000')].

    Formato das colunas de CID nos .CNV do TabWin. Início completa com 0 e fim com 9
    até 4 caracteres, para comparar como texto qualquer código de 3 ou 4 caracteres.
    """
    saida = []
    for item in codigos.replace(" ", "").split(","):
        ini, _, fim = item.partition("-")
        saida.append((ini.ljust(4, "0"), (fim or ini).ljust(4, "9")))
    return saida


def dentro(cid: str, faixas_: list[tuple[str, str]]) -> bool:
    """CID ('J45', 'J45.0', 'J450') em alguma das faixas."""
    c = cid.replace(".", "").upper()
    if len(c) == 3:  # categoria: basta uma subcategoria dela estar na lista
        return any(ini[:3] <= c <= fim[:3] for ini, fim in faixas_)
    return any(ini <= c <= fim for ini, fim in faixas_)


def gerar_icsap() -> None:
    pacote = zipfile.ZipFile(io.BytesIO(_baixar(FTP + "Auxiliar/TAB_SIH.zip")))
    cnv = pacote.read("CNV/SENSIVEISATB01.CNV").decode("latin1")
    with ICSAP_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["grupo", "cid_inicio", "cid_fim"])
        for linha in cnv.splitlines()[1:]:
            # "  1  13  1.12 Tuberculose Pulmonar    A15 -A159,A16 -A169"
            m = re.match(r"^\s*\d*\s+\d+\s+(.+?)\s{2,}([A-Z][0-9A-Z ,\-]+)$", linha)
            if m and m.group(2).strip() != "----":
                for ini, fim in faixas(m.group(2)):
                    w.writerow([m.group(1).strip(), ini, fim])
    print(f"{ICSAP_CSV.name}: lista ICSAP gravada.")


# --- internações por CID ---


def _meses_completos() -> list[str]:
    """Os `MESES` AAMM mais recentes com arquivo RD de todas as UFs."""
    listagem = _baixar(FTP + "Dados/").decode("latin1")
    por_mes = collections.Counter(re.findall(r"RD[A-Z]{2}(\d{4})\.dbc", listagem))
    return sorted(m for m, n in por_mes.items() if n == UFS)[-MESES:]


def diagnosticos(dbf: bytes) -> collections.Counter:
    """Categoria CID (3 caracteres) do DIAG_PRINC de cada internação do DBF.

    DBF tem registro de largura fixa: basta achar o deslocamento do campo no cabeçalho
    e fatiar. Montar o registro inteiro (~100 colunas, como faz o dbfread) deixava a
    coleta presa na CPU — ~1 h para um ano de Brasil.
    """
    n, cabecalho, tamanho = struct.unpack_from("<IHH", dbf, 4)
    pos, desloc = 32, 1  # o byte 0 de cada registro é a marca de apagado
    while dbf[pos] != 0x0D:
        if dbf[pos : pos + 11].split(b"\0")[0] == b"DIAG_PRINC":
            break
        desloc += dbf[pos + 16]
        pos += 32
    else:
        raise ValueError("DBF sem o campo DIAG_PRINC")
    inicio = cabecalho + desloc
    return collections.Counter(
        cid
        for i in range(n)
        if dbf[cabecalho + i * tamanho] != 0x2A  # "*": registro apagado
        and (cid := dbf[inicio + i * tamanho : inicio + i * tamanho + 3].decode("latin1").strip())
    )


def _contar(nome: str) -> collections.Counter:
    import datasus_dbc

    with tempfile.TemporaryDirectory() as tmp:
        dbc, dbf = Path(tmp, "a.dbc"), Path(tmp, "a.dbf")
        dbc.write_bytes(_baixar(FTP + "Dados/" + nome))
        datasus_dbc.decompress(str(dbc), str(dbf))
        return diagnosticos(dbf.read_bytes())


def gerar_prevalencia() -> None:
    meses = _meses_completos()
    listagem = _baixar(FTP + "Dados/").decode("latin1")
    arquivos = sorted(set(re.findall(rf"RD[A-Z]{{2}}(?:{'|'.join(meses)})\.dbc", listagem)))
    print(f"{len(arquivos)} arquivos, {meses[0]}–{meses[-1]} (AAMM).", file=sys.stderr)
    total = collections.Counter()
    with ThreadPoolExecutor(max_workers=4) as pool:  # espera de rede; o parse é leve
        for n, contagem in enumerate(pool.map(_contar, arquivos), 1):
            total += contagem
            if n % 27 == 0:
                print(f"  {n} / {len(arquivos)}", file=sys.stderr)
    with PREVALENCIA_CSV.open("w", newline="") as f:
        f.write(f"# SIH/SUS, internações por diagnóstico principal, {meses[0]} a {meses[-1]} (AAMM)\n")
        w = csv.writer(f)
        w.writerow(["cid3", "internacoes"])
        w.writerows(sorted(total.items()))
    print(f"{PREVALENCIA_CSV.name}: {sum(total.values())} internações em {len(total)} categorias.")


# --- leitura (usada por rag.catalogo) ---


def carregar_icsap() -> list[tuple[str, str]]:
    with ICSAP_CSV.open() as f:
        return [(r["cid_inicio"], r["cid_fim"]) for r in csv.DictReader(f)]


def carregar_prevalencia() -> dict[str, int]:
    with PREVALENCIA_CSV.open() as f:
        linhas = (l for l in f if not l.startswith("#"))
        return {r["cid3"]: int(r["internacoes"]) for r in csv.DictReader(linhas)}


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        fx = faixas("A15 -A159,A171-A179,G000")
        assert fx == [("A150", "A159"), ("A171", "A179"), ("G000", "G000")]
        assert dentro("A15", fx) and dentro("A15.3", fx) and dentro("a172", fx)
        assert not dentro("A170", fx) and not dentro("A16", fx)
        assert dentro("G00", fx), "categoria conta se alguma subcategoria está na lista"
        assert not dentro("G001", fx)

        # DBF mínimo: 2 campos (SEXO C1, DIAG_PRINC C4), 3 registros, o do meio apagado.
        campos = b"".join(
            nome.ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([tam]) + b"\0" * 15
            for nome, tam in ((b"SEXO", 1), (b"DIAG_PRINC", 4))
        )
        cab, reg = 32 + len(campos) + 1, 1 + 1 + 4
        dbf = struct.pack("<BBBBIHH", 3, 0, 0, 0, 3, cab, reg).ljust(32, b"\0") + campos + b"\r"
        dbf += b" 1J450" + b"*3I219" + b" 1J459" + b"\x1a"
        assert diagnosticos(dbf) == collections.Counter({"J45": 2}), "pula o apagado, corta em 3"
        print("OK: faixas CID do TabWin e leitura do DIAG_PRINC no DBF.")
    else:
        gerar_icsap()
        gerar_prevalencia()
